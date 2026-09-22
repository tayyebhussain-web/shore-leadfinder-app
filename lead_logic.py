"""
Places API Aufrufe + Erkennungs-Heuristiken (Konkurrenzsystem, Neu-Erkennung,
Review-Pain-Points, Score, Filialketten). Wird von app.py verwendet.
"""

import re
import time
from collections import Counter, defaultdict
from datetime import datetime
from itertools import combinations
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

SEARCH_URL = "https://places.googleapis.com/v1/places:searchText"
DETAILS_URL = "https://places.googleapis.com/v1/places/{place_id}"
REQUEST_TIMEOUT = 10
CET = ZoneInfo("Europe/Berlin")


def now_cet_sortable() -> str:
    """ISO-artiger, lexikographisch sortierbarer Zeitstempel in CET/CEST (z.B. '2026-09-18 18:52:00')."""
    return datetime.now(CET).strftime("%Y-%m-%d %H:%M:%S")

# Woher ein Lead stammt. Aktuell gibt es nur einen Beschaffungsweg (Google Places), das Feld ist aber vorbereitet
# fuer weitere Quellen (z.B. Treatwell-Verzeichnis, Northdata), damit spaeter erkennbar bleibt, woher ein
# einzelner Lead kam. Bekannte Werte stehen zusaetzlich in static/app.js (LEAD_SOURCES) fuer den Spaltenfilter.
LEAD_SOURCE_GOOGLE = "Google Maps API"

ICP_CATEGORIES = [
    "Kosmetikstudio",
    "Friseur",
    "Nagelstudio",
    "Botox / Medical Beauty",
    "Bleaching-Zentrum",
    "Wellness / Spa",
    "Brautmode",
    "Physiotherapie",
    "Tierarzt / Hundesalon",
    "Tattoo-Studio",
    "Massage-Praxis",
]

COMPETITOR_SIGNATURES = {
    "Fresha": ["fresha.com", "fresha.de", "book with fresha", "powered by fresha"],
    "Treatwell": ["treatwell.de", "treatwell.com", "treatwell.at", "treatwell.ch", "trea.tw"],
    "Planity": ["planity.com"],
    "SumUp": ["sumup.com", "sumup.de", "pay.sumup"],
    "Calendly": ["calendly.com"],
    "Booksy": ["booksy.com"],
    "Salonized": ["salonized.com"],
    "Beautinda": ["beautinda.de", "beautinda.com", "book with beautinda", "powered by beautinda"],
    "Shortcuts": ["shortcuts.com"],
    "Timify": ["timify.com"],
    "Phorest": ["phorest.com"],
    "Terminland": ["terminland.de", "terminland.com"],
    "Salonkee": ["salonkee.de", "salonkee.lu", "salonkee.com"],
    "Timely": ["gettimely.com"],
    "Vagaro": ["vagaro.com"],
    "Studiobookr": ["studiobookr.com"],
    # Zahnarzt-/Arztpraxen (Doctolib, Dr. Flex, Jameda, Studiobookr in den eigenen Daten gesehen;
    # Samedi, Clickdoc, Doctena, Dentolo dort nicht gesehen, aber bekannte Anbieter)
    "Doctolib": ["doctolib.de", "doctolib.com", "doctolib.fr"],
    "Jameda": ["jameda.de", "jameda-elements.de"],
    "Dr. Flex": ["dr-flex.de", "dr-flex", "drflex"],
    "Samedi": ["samedi.de"],
    "Clickdoc": ["clickdoc.de"],
    "Doctena": ["doctena.com", "doctena.de", "doctena.lu"],
    "Dentolo": ["dentolo.de"],
    # Echte Shore-Buchungsadresse: connect.shore.com/bookings/<name>/services
    "Shore (bereits Kunde)": ["connect.shore.com", "shore.com/bookings"],
}

# --- ICP-Scoring ---------------------------------------------------------
# Gewichtung pro Kategorie (0-30 Punkte). Das ist eine Annahme auf Basis von
# Ticketgroesse/Zahlungsverhalten aus den bisherigen Shore-Pitches (z.B.
# Brautmode: Anzahlungen auf hochpreisige Massanfertigungen; Botox/Medical
# Beauty: hoeherer Warenkorb) - NICHT durch harte Zahlen abgesichert.
# Am besten kurz mit deinen bisherigen Abschluessen/Deal-Groessen abgleichen
# und hier direkt anpassen, das ist der Hebel mit dem groessten Effekt auf
# den Score.
CATEGORY_WEIGHTS = {
    "Botox / Medical Beauty": 30,
    "Brautmode": 30,
    "Wellness / Spa": 25,
    "Bleaching-Zentrum": 22,
    "Kosmetikstudio": 22,
    "Physiotherapie": 20,
    "Nagelstudio": 18,
    "Friseur": 18,
    "Massage-Praxis": 18,
    "Tattoo-Studio": 15,
    "Tierarzt / Hundesalon": 15,
}
DEFAULT_CATEGORY_WEIGHT = 15  # fuer frei eingegebene Kategorien, die nicht in der Liste stehen


OPENING_STATUS_BONUS = {
    "Bald eröffnend": 20,  # FUTURE_OPENING - hat garantiert noch kein Buchungssystem
    "Neu eröffnet": 15,    # operational + wenige Bewertungen - hat vermutlich noch keins
    "Etabliert": 0,
}


def detect_opening_status(business_status: str, rating_count: int) -> str:
    if business_status == "FUTURE_OPENING":
        return "Bald eröffnend"
    if detect_likely_new(rating_count, business_status):
        return "Neu eröffnet"
    return "Etabliert"


def format_opening_date(opening_date: dict) -> str:
    if not opening_date:
        return ""
    year = opening_date.get("year")
    month = opening_date.get("month")
    day = opening_date.get("day")
    if not year:
        return ""
    parts = [str(year)]
    if month:
        parts.insert(0, f"{month:02d}")
        if day:
            parts.insert(0, f"{day:02d}")
    return ".".join(parts) if len(parts) > 1 else parts[0]


def compute_icp_score(category: str, rating_count: int, competitor: str,
                       chain_flag: bool, pain_points: list, opening_status: str = "Etabliert") -> tuple:
    """Gibt (score 0-100, tier 'A'/'B'/'C') zurueck.

    Zusammensetzung:
      - Kategorie-Fit          bis 30 Punkte
      - Kein Konkurrenzsystem  bis 25 Punkte (das eigentliche Kaufsignal)
      - Kundenvolumen-Proxy    bis 20 Punkte (ueber Anzahl Bewertungen)
      - Filialkette (3-9)      bis 15 Punkte (mehr MRR-Potenzial pro Deal)
      - Review-Pain-Point      bis 10 Punkte (konkreter Anruf-Aufhaenger)
      - Bald eröffnend/Neu     bis 20 Punkte (garantiert/vermutlich noch kein Buchungssystem)
    """
    score = 0
    score += CATEGORY_WEIGHTS.get(category, DEFAULT_CATEGORY_WEIGHT)

    if not competitor:
        score += 25

    if rating_count >= 20:
        score += 20
    elif rating_count >= 3:
        score += 10

    if chain_flag:
        score += 15

    if pain_points:
        score += 10

    score += OPENING_STATUS_BONUS.get(opening_status, 0)

    score = min(score, 100)

    if score >= 65:
        tier = "A"
    elif score >= 40:
        tier = "B"
    else:
        tier = "C"

    return score, tier


PAIN_POINT_PATTERNS = {
    "Schwer erreichbar": [
        r"schwer erreichbar", r"nicht erreichbar", r"niemand (geht|nimmt) ans telefon",
        r"kein(e)? r(ü|ue)ckruf", r"nie(mand)? erreicht", r"telefonisch nicht",
    ],
    "Terminvergabe kompliziert": [
        r"termin.{0,15}(schwierig|kompliziert|umst(ä|ae)ndlich)",
        r"lange (auf einen termin )?gewartet", r"keine termine (frei|verf(ü|ue)gbar)",
        r"schwer einen termin",
    ],
    "Keine Rückmeldung": [
        r"keine (r(ü|ue)ckmeldung|antwort)", r"nicht (geantwortet|zur(ü|ue)ckgemeldet)",
        r"nachricht.{0,15}ignoriert",
    ],
}


def geocode_region(api_key: str, region: str) -> dict:
    """Loest einen Ortsnamen/PLZ ueber die Places Text Search (ohne Kategorie) in Koordinaten auf.
    Gibt None zurueck, wenn nichts gefunden wurde."""
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": api_key,
        "X-Goog-FieldMask": "places.location",
    }
    resp = requests.post(SEARCH_URL, json={"textQuery": region, "languageCode": "de"},
                          headers=headers, timeout=REQUEST_TIMEOUT)
    if resp.status_code != 200:
        raise RuntimeError(f"Places API Fehler {resp.status_code}: {resp.text[:300]}")
    places = resp.json().get("places", [])
    if not places:
        return None
    return places[0].get("location")


def search_places(api_key: str, query: str, max_results: int, location_bias: dict = None) -> list:
    results = []
    page_token = None
    field_mask = ",".join([
        "places.id", "places.displayName", "places.formattedAddress",
        "places.internationalPhoneNumber", "places.nationalPhoneNumber",
        "places.websiteUri", "places.rating", "places.userRatingCount",
        "places.businessStatus", "places.currentOpeningHours.openNow", "places.openingDate",
        "nextPageToken",
    ])
    while len(results) < max_results:
        body = {"textQuery": query, "languageCode": "de"}
        if location_bias:
            body["locationBias"] = {"circle": location_bias}
        if page_token:
            body["pageToken"] = page_token
        headers = {
            "Content-Type": "application/json",
            "X-Goog-Api-Key": api_key,
            "X-Goog-FieldMask": field_mask,
        }
        resp = requests.post(SEARCH_URL, json=body, headers=headers, timeout=REQUEST_TIMEOUT)
        if resp.status_code != 200:
            raise RuntimeError(f"Places API Fehler {resp.status_code}: {resp.text[:300]}")
        data = resp.json()
        places = data.get("places", [])
        results.extend(places)
        page_token = data.get("nextPageToken")
        if not page_token:
            break
        time.sleep(2)
    return results[:max_results]


def get_reviews(api_key: str, place_id: str) -> list:
    headers = {"X-Goog-Api-Key": api_key, "X-Goog-FieldMask": "reviews"}
    url = DETAILS_URL.format(place_id=place_id)
    resp = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT)
    if resp.status_code != 200:
        return []
    reviews = resp.json().get("reviews", [])
    return [(r.get("text") or {}).get("text", "") for r in reviews if (r.get("text") or {}).get("text")]


def fetch_website_html(url: str) -> str:
    if not url:
        return ""
    # Bei Zertifikatsfehlern (z. B. abgelaufenes Zertifikat) einmal ohne Pruefung lesen: es wird nur
    # oeffentliches HTML gelesen, es werden keine Zugangsdaten gesendet.
    for verify in (True, False):
        try:
            resp = requests.get(url, timeout=REQUEST_TIMEOUT, headers={"User-Agent": "Mozilla/5.0"}, verify=verify)
            return resp.text.lower() if resp.status_code == 200 else ""
        except requests.exceptions.SSLError:
            continue
        except requests.RequestException:
            return ""
    return ""


def detect_likely_new(rating_count: int, business_status: str) -> bool:
    return business_status == "OPERATIONAL" and rating_count < 5


def detect_competitor(website: str, website_html: str, review_texts: list) -> str:
    haystacks = [website.lower() if website else "", website_html]
    haystacks.extend(t.lower() for t in review_texts)
    combined = " ".join(haystacks)
    found = [system for system, signatures in COMPETITOR_SIGNATURES.items()
             if any(sig in combined for sig in signatures)]
    return ", ".join(found)


def merge_systems(old: str, new: str) -> str:
    """Vereinigt zwei kommagetrennte Systemlisten ohne Dubletten, sortiert nach COMPETITOR_SIGNATURES."""
    names = {s.strip() for s in f"{old or ''},{new or ''}".split(",") if s.strip()}
    order = list(COMPETITOR_SIGNATURES)
    return ", ".join(sorted(names, key=lambda s: order.index(s) if s in order else len(order)))


def detect_pain_points(review_texts: list) -> list:
    combined = " ".join(t.lower() for t in review_texts)
    found = []
    for label, patterns in PAIN_POINT_PATTERNS.items():
        for pattern in patterns:
            if re.search(pattern, combined):
                found.append(label)
                break
    return found


EMAIL_PATTERN = re.compile(r"\b[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9\-]+(?:\.[a-zA-Z0-9\-]+)*\.[a-zA-Z]{2,24}\b")
# Ausschluesse: technische/generische Adressen, die auf fast jeder Website vorkommen, aber nicht zum Betrieb gehoeren
EMAIL_JUNK_LOCAL = {"wordpress", "sentry", "wixpress", "example", "godaddy", "domain", "test", "noreply",
                    "no-reply", "your", "youremail", "email", "name", "datenschutz", "dsgvo", "privacy",
                    "jobs", "karriere", "bewerbung", "presse", "press", "compliance", "legal", "impressum",
                    "webmaster", "admin", "security", "abuse", "sicherheit", "medizinproduktesicherheit",
                    "hr", "recruiting"}
EMAIL_JUNK_DOMAIN = {"sentry.io", "wixpress.com", "example.com", "godaddy.com", "schema.org", "w3.org",
                     "cloudflare.com", "google.com", "gstatic.com", "domain.com", "wordpress.org",
                     "wordpress.com", "sentry-cdn.com", "yoast.com", "email.com", "email.de",
                     "personio.de", "personio.com", "datenschutz-berlin.de"}


def _email_domain_junk(domain: str) -> bool:
    return any(domain == d or domain.endswith("." + d) for d in EMAIL_JUNK_DOMAIN)


def detect_email(website: str, website_html: str) -> str:
    """Plausibelste Kontakt-E-Mail aus dem Website-HTML: zuerst mailto-Links, dann rohe Adressen im Text.
    mailto-Werte werden gegen dasselbe Muster wie Text-Treffer geprueft, damit angehaengte Satzzeichen oder
    Platzhalter (z.B. "your@email") nicht durchrutschen. Adressen auf der EIGENEN Domain des Betriebs (z.B.
    info@dental21-kudamm.de bei website dental21-kudamm.de) gehen vor Adressen auf fremden Domains (Buchungs-
    portale, Datenschutz-Sammeladressen, HR-Tools) - so wird nicht zufaellig die erstbeste E-Mail im HTML
    gewaehlt, wenn eine Seite mehrere fuehrt. Gibt "" zurueck, wenn nichts Plausibles gefunden wurde."""
    if not website_html:
        return ""
    # In eingebettetem JSON/JS steht ein Anfuehrungszeichen manchmal als literales " statt ": das klebt
    # sonst als "u0022" am Anfang der naechsten E-Mail (z.B. "webmaster@...).
    website_html = website_html.replace("\\u0022", '"')
    raw = [m.group(1) for m in re.finditer(r'mailto:([^"\'\s?&<>]+)', website_html, re.I)]
    raw += EMAIL_PATTERN.findall(website_html)

    own_domain = re.sub(r"^www\.", "", urlparse(website if "//" in (website or "") else "//" + (website or "")).netloc.lower())
    own, other, seen = [], [], set()
    for r in raw:
        m = EMAIL_PATTERN.search(r)
        if not m:
            continue
        addr = m.group(0)
        low = addr.lower()
        if low in seen:
            continue
        local, _, domain = low.partition("@")
        if not domain or _email_domain_junk(domain) or local in EMAIL_JUNK_LOCAL:
            continue
        seen.add(low)
        (own if own_domain and (domain == own_domain or domain.endswith("." + own_domain)) else other).append(addr)
    picks = own or other
    return picks[0] if picks else ""


def compute_score(competitor: str, likely_new: bool) -> str:
    if not competitor and likely_new:
        return "Heiss"
    if not competitor:
        return "Mittel"
    return "Niedrig"


# --- Kettenerkennung -----------------------------------------------------
# Kette = mindestens 2 bekannte Standorte derselben Marke. Zwei Betriebe gehoeren zusammen, wenn
#   (1) ihre Website dieselbe Adresse hat, oder
#   (2) ihre Website denselben Markenanfang hat (dental21-kudamm.de / dental21-pankow.de), oder
#   (3) ihr Markenkern im Namen gleich ist (nach Entfernen von Rechtsform, Ortsnamen und Allerweltswoertern),
#       ausser beide Websites existieren und widersprechen sich.
# Gezaehlt wird ueber die ganze Datenbank, nicht nur ueber einen Suchlauf.
CHAIN_STOPWORDS = set("""
gmbh ug ek inh filiale standort mvz ohg kg ag co und and the die der das ihr ihre in im am an bei by von vom zu zum zur
fuer für mit ohne aus berlin wien münchen muenchen zürich zuerich hamburg köln koeln frankfurt stuttgart düsseldorf
duesseldorf leipzig dresden hannover bremen mitte pankow charlottenburg schöneberg schoeneberg kreuzberg friedrichshain
neukölln neukoelln prenzlauer berg wedding steglitz spandau tempelhof lichtenberg reinickendorf zehlendorf wilmersdorf
moabit kudamm nails nail beauty kosmetik kosmetikstudio kosmetikinstitut studio salon spa wellness massage friseur
friseure coiffeur hair haar haare barber lashes lash brows brow cosmetic cosmetics tattoo piercing zahnarzt zahnärzte
zahnaerzte zahnarztpraxis zahnzentrum zahnmedizin zahnaufhellung bleaching praxis clinic klinik center zentrum lounge bar
boutique institut physiotherapie dr med dent prof smile style glow schön schoen team house haus world nagelstudio
""".split())
# Adressen, die sich viele fremde Betriebe teilen (Social Media, Website-Baukaesten, Verzeichnisse, Kurzlinks).
# Gleiche Adresse hier beweist keine Kette. Suffix-Vergleich: "x.ivof.com" gehoert zu "ivof.com".
CHAIN_SHARED_DOMAINS = ("facebook.com", "instagram.com", "linktr.ee", "google.com", "business.site", "wa.me",
                        "tiktok.com", "trea.tw", "ivof.com", "wixsite.com", "jimdofree.com", "jimdosite.com",
                        "squarespace.com", "weebly.com", "godaddysites.com", "strikingly.com", "carrd.co",
                        "beacons.ai", "wordpress.com", "blogspot.com", "myshopify.com")


def _name_core(name: str) -> str:
    tokens = [t for t in re.findall(r"[a-zäöüß0-9]+", (name or "").lower()) if len(t) > 1 and t not in CHAIN_STOPWORDS]
    return " ".join(sorted(tokens))


def _chain_host(url: str) -> str:
    """Website-Adresse ohne www. Gibt "" zurueck fuer Social-Media-Seiten und Buchungsportale (dort teilen
    sich viele fremde Betriebe dieselbe Adresse)."""
    if not url:
        return ""
    host = urlparse(url if "//" in url else "//" + url).netloc.lower().split(":")[0]
    host = host[4:] if host.startswith("www.") else host
    if any(host == d or host.endswith("." + d) for d in CHAIN_SHARED_DOMAINS):
        return ""
    if any(sig in host for sigs in COMPETITOR_SIGNATURES.values() for sig in sigs if "." in sig):
        return ""
    return host


def _domain_brand(host: str) -> str:
    """Markenanfang einer Adresse mit Bindestrich: dental21-kudamm.de -> dental21."""
    parts = host.split(".")
    label = parts[-2] if len(parts) >= 2 else ""
    brand = label.split("-")[0] if "-" in label else ""
    return brand if len(brand) >= 5 and brand not in CHAIN_STOPWORDS and not brand.isdigit() else ""


def chain_sizes(leads) -> dict:
    """leads: Iterable von Dicts mit place_id, name, website. Gibt {place_id: Anzahl Standorte der Gruppe} zurueck
    (1 = Einzelbetrieb)."""
    items = list(leads)
    parent = list(range(len(items)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    hosts = [_chain_host(l.get("website")) for l in items]
    brands = [_domain_brand(h) for h in hosts]
    cores = [_name_core(l.get("name")) for l in items]

    buckets = defaultdict(list)
    for i in range(len(items)):
        if hosts[i]:
            buckets[("host", hosts[i])].append(i)
        if brands[i]:
            buckets[("brand", brands[i])].append(i)
    for members in buckets.values():
        for other in members[1:]:
            union(members[0], other)

    by_core = defaultdict(list)
    for i, core in enumerate(cores):
        if core:
            by_core[core].append(i)
    for members in by_core.values():
        for a, b in combinations(members, 2):
            websites_contradict = hosts[a] and hosts[b] and hosts[a] != hosts[b] and (not brands[a] or brands[a] != brands[b])
            if not websites_contradict:
                union(a, b)

    group_size = Counter(find(i) for i in range(len(items)))
    return {items[i]["place_id"]: group_size[find(i)] for i in range(len(items))}


def flag_chains(leads: list, known: list = None) -> None:
    """Setzt chain_flag und chain_count an den neuen Leads (in-place). known = bereits gespeicherte Leads,
    damit auch Standorte aus frueheren Suchen mitzaehlen."""
    combined = {l["place_id"]: l for l in (known or [])}
    combined.update({l["place_id"]: l for l in leads})
    sizes = chain_sizes(combined.values())
    for lead in leads:
        count = sizes.get(lead["place_id"], 1)
        lead["chain_count"] = count
        lead["chain_flag"] = count >= 2


def enrich_place(api_key: str, place: dict, region: str, category: str) -> dict:
    """Ein einzelnes Places-API-Ergebnis anreichern (Reviews, Website, Heuristiken)."""
    place_id = place.get("id", "")
    name = (place.get("displayName") or {}).get("text", "unbekannt")
    website = place.get("websiteUri", "")
    phone = place.get("nationalPhoneNumber") or place.get("internationalPhoneNumber") or ""
    rating_count = place.get("userRatingCount", 0) or 0

    review_texts = get_reviews(api_key, place_id)
    website_html = fetch_website_html(website) if website else ""

    business_status = place.get("businessStatus", "")
    likely_new = detect_likely_new(rating_count, business_status)
    opening_status = detect_opening_status(business_status, rating_count)
    opening_date = format_opening_date(place.get("openingDate"))
    competitor = detect_competitor(website, website_html, review_texts)
    pain_points = detect_pain_points(review_texts)
    email = detect_email(website, website_html)
    score = compute_score(competitor, likely_new)

    return {
        "place_id": place_id,
        "name": name,
        "address": place.get("formattedAddress", ""),
        "phone": phone,
        "website": website,
        "email": email,
        "lead_source": LEAD_SOURCE_GOOGLE,
        "rating": place.get("rating"),
        "rating_count": rating_count,
        "business_status": business_status,
        "open_now": (place.get("currentOpeningHours") or {}).get("openNow"),
        "category_query": category,
        "region_query": region,
        "likely_new": likely_new,
        "opening_status": opening_status,
        "opening_date": opening_date,
        "competitor_system": competitor,
        "pain_points": ", ".join(pain_points),
        "score": score,
        "chain_flag": False,  # wird in finalize_leads() nach der Chain-Erkennung gesetzt
        "first_seen": now_cet_sortable(),
        "icp_score": 0,
        "icp_tier": "",
        "status": "Neu",
        "notes": "",
    }


def finalize_leads(leads: list, known: list = None) -> None:
    """Nach enrich_place() fuer eine ganze Liste aufrufen: setzt Filialketten-Flag
    und berechnet danach den ICP-Score (der die Ketten-Info braucht)."""
    flag_chains(leads, known)
    for lead in leads:
        pain_points = [p for p in (lead.get("pain_points") or "").split(", ") if p]
        icp_score, icp_tier = compute_icp_score(
            category=lead["category_query"],
            rating_count=lead.get("rating_count") or 0,
            competitor=lead.get("competitor_system") or "",
            chain_flag=lead.get("chain_flag", False),
            pain_points=pain_points,
            opening_status=lead.get("opening_status", "Etabliert"),
        )
        lead["icp_score"] = icp_score
        lead["icp_tier"] = icp_tier
