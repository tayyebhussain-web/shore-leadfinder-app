"""
Places API Aufrufe + Erkennungs-Heuristiken (Konkurrenzsystem, Neu-Erkennung,
Review-Pain-Points, Score, Filialketten). Wird von app.py verwendet.
"""

import re
import time
from collections import defaultdict
from datetime import datetime
from zoneinfo import ZoneInfo

import requests

SEARCH_URL = "https://places.googleapis.com/v1/places:searchText"
DETAILS_URL = "https://places.googleapis.com/v1/places/{place_id}"
REQUEST_TIMEOUT = 10
CET = ZoneInfo("Europe/Berlin")


def now_cet_sortable() -> str:
    """ISO-artiger, lexikographisch sortierbarer Zeitstempel in CET/CEST (z.B. '2026-09-18 18:52:00')."""
    return datetime.now(CET).strftime("%Y-%m-%d %H:%M:%S")

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
    "Treatwell": ["treatwell.de", "treatwell.com", "treatwell.at", "treatwell.ch"],
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
    "Shore (bereits Kunde)": ["shore.com/book", "book.shore.com", "shore-booking"],
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
    try:
        resp = requests.get(url, timeout=REQUEST_TIMEOUT, headers={"User-Agent": "Mozilla/5.0"})
        if resp.status_code == 200:
            return resp.text.lower()
    except requests.RequestException:
        pass
    return ""


def detect_likely_new(rating_count: int, business_status: str) -> bool:
    return business_status == "OPERATIONAL" and rating_count < 5


def detect_competitor(website: str, website_html: str, review_texts: list) -> str:
    haystacks = [website.lower() if website else "", website_html]
    haystacks.extend(t.lower() for t in review_texts)
    combined = " ".join(haystacks)
    for system, signatures in COMPETITOR_SIGNATURES.items():
        for sig in signatures:
            if sig in combined:
                return system
    return ""


def detect_pain_points(review_texts: list) -> list:
    combined = " ".join(t.lower() for t in review_texts)
    found = []
    for label, patterns in PAIN_POINT_PATTERNS.items():
        for pattern in patterns:
            if re.search(pattern, combined):
                found.append(label)
                break
    return found


def compute_score(competitor: str, likely_new: bool) -> str:
    if not competitor and likely_new:
        return "Heiss"
    if not competitor:
        return "Mittel"
    return "Niedrig"


def normalize_name_for_chain_check(name: str) -> str:
    n = name.lower()
    n = re.sub(r"\b(gmbh|ug|e\.?k\.?|inh\.?|filiale|standort)\b", "", n)
    n = re.sub(r"\d+", "", n)
    n = re.sub(r"[^a-z\s]", "", n)
    return " ".join(n.split())


def flag_chains(leads: list) -> None:
    """leads: list of dicts with 'name' key; sets 'chain_flag' in place."""
    groups = defaultdict(list)
    for lead in leads:
        key = normalize_name_for_chain_check(lead["name"])
        if key:
            groups[key].append(lead)
    for group in groups.values():
        if 3 <= len(group) <= 9:
            for lead in group:
                lead["chain_flag"] = True


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
    score = compute_score(competitor, likely_new)

    return {
        "place_id": place_id,
        "name": name,
        "address": place.get("formattedAddress", ""),
        "phone": phone,
        "website": website,
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


def finalize_leads(leads: list) -> None:
    """Nach enrich_place() fuer eine ganze Liste aufrufen: setzt Filialketten-Flag
    und berechnet danach den ICP-Score (der die Ketten-Info braucht)."""
    flag_chains(leads)
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
