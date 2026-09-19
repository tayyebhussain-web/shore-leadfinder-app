# Lead-Finder Baupläne — provider-unabhängig, für Claude Code

Zweck: Dieses Dokument beschreibt das komplette System so genau, dass Claude Code es aus dem Nichts nachbauen kann —
aber **ohne Bindung an Google**. Die Datenquelle steckt hinter einem Adapter, alles Branchenspezifische steht in einer
Config-Datei. Damit baust du dieselbe Maschine für andere Branchen, Länder oder Datenquellen.

Referenz-Implementierung (Google Places, Beauty/Wellness, DACH): dieses Repo. Wenn du Claude Code den Repo-Ordner
gibst, kann es jede Stelle 1:1 nachlesen. Dieses Dokument ist die abstrahierte, portable Fassung.

---

## 0. So benutzt du das Dokument

1. Neuen leeren Ordner anlegen, `claude` starten.
2. Abschnitt **15 (Phasen-Prompts)** der Reihe nach einfügen. Jede Phase hat ein Abnahme-Kriterium — erst weiter, wenn es erfüllt ist.
3. Für andere Branche/Datenquelle nur Abschnitt **13 (Config)** und den Adapter (Abschnitt 3) austauschen.
4. Beim ersten Prompt zusätzlich den ganzen Rest dieses Dokuments als Kontext einfügen (oder `BUILD_SPEC.md` im Ordner ablegen und "lies BUILD_SPEC.md" sagen).

---

## 1. Was das System tut (Produkt in 10 Sätzen)

1. Du gibst **Orte** (Stadt/Bezirk/PLZ, mehrere kommagetrennt), eine **Kategorie** und optional einen **Umkreis in km** ein.
2. Das System holt passende Unternehmen von einer Datenquelle (Provider).
3. Jedes Unternehmen wird **angereichert**: Website-HTML, Bewertungstexte, Öffnungsstatus.
4. Aus diesen Rohdaten werden **Signale** berechnet: nutzt schon ein Buchungs-/Konkurrenzsystem? Neu eröffnet? Kette? Pain-Points in Bewertungen?
5. Aus den Signalen entsteht ein **ICP-Score 0–100 %** und ein **Tier A/B/C** (A = grün = zuerst anrufen).
6. Alles landet dauerhaft in **SQLite**. Duplikate sind unmöglich (Primary Key = ID der Datenquelle).
7. Jede Suche wird gemerkt; **Sync** wiederholt alle gemerkten Suchen und findet neue Unternehmen.
8. UI: drei aufklappbare Tabellen **Neu / Alt / Exportiert** mit Spaltenfiltern, Volltextsuche, Sortierung.
9. **Export** (CSV, Excel, HubSpot-CSV) verschiebt exportierte Leads automatisch nach "Exportiert".
10. **Aktivitäts-Log mit Undo/Redo** für alles Ändernde (dauerhaft in der DB).

Lokale Web-App, Flask + SQLite + Vanilla JS. Kein Build-Step, keine Frameworks, keine Accounts.

---

## 2. Architektur

```
app/
  app.py              Flask-Routen (dünn, keine Logik)
  db.py               SQLite: Schema, Migrationen, alle Queries, Log/Undo
  pipeline.py         search -> enrich -> detect -> score -> finalize (Orchestrierung)
  detectors.py        reine Funktionen: competitor, pain_points, opening_status, chains
  scoring.py          reine Funktion: compute_score(signals, config) -> (score, tier)
  exports.py          CSV / XLSX / HubSpot-CSV
  config.py           ALLES Branchen-/Kundenspezifische (Kategorien, Gewichte, Signaturen, Regex)
  providers/
    base.py           abstrakte Klasse Provider
    google_places.py  Implementierung 1
    osm_overpass.py   Implementierung 2 (kostenlos, ohne Key)
    ...               weitere
  static/app.js  static/style.css  templates/index.html
  leads.db  (gitignored)
```

Regeln:
- `detectors.py` und `scoring.py` sind **reine Funktionen** (kein I/O) → trivial testbar.
- Nur `providers/*` sprechen mit externen APIs. Nur `pipeline.py` kennt Provider + Detectors.
- `app.py` enthält keine Geschäftslogik. Routen rufen `pipeline`/`db` auf und geben JSON zurück.
- Alle Zeiten Europe/Berlin, gespeichert als sortierbarer String `YYYY-MM-DD HH:MM:SS`.

---

## 3. Provider-Adapter (der Teil, der Google ersetzt)

### 3.1 Interface (exakt so bauen)

```python
class Provider:
    name: str
    max_radius_km: float | None      # Grenze des Providers (Google: 50). None = unbegrenzt
    max_reviews: int                 # wie viele Reviews holbar (Google: 5)

    def geocode(self, region: str) -> tuple[float, float] | None: ...
    def search(self, category: str, region: str, count: int,
               center: tuple[float, float] | None, radius_km: float) -> list[RawPlace]: ...
    def reviews(self, place_id: str) -> list[str]: ...   # nur Texte; [] wenn nicht unterstützt
```

`RawPlace` (Dataclass) — der **einzige** Datentyp, den die Pipeline kennt:

```python
@dataclass
class RawPlace:
    id: str                 # stabil + eindeutig innerhalb des Providers (mit Prefix: "gp:...", "osm:node/123")
    name: str
    address: str
    phone: str
    website: str
    rating: float | None
    rating_count: int
    business_status: str    # normalisiert: OPERATIONAL | CLOSED_TEMPORARILY | CLOSED_PERMANENTLY | FUTURE_OPENING | UNKNOWN
    open_now: bool | None
    opening_date: dict | None   # {"year":..,"month":..,"day":..} nur wenn bekannt
    lat: float | None
    lng: float | None
    source_url: str         # Deep-Link zum Eintrag beim Provider (optional)
```

Jeder Provider **normalisiert** in dieses Format. Alles danach ist provider-unabhängig.
ID-Prefix pro Provider verhindert Kollisionen, wenn du später mehrere Quellen mischst.

### 3.2 Kandidaten (vor dem Bau die aktuelle Doku/Preise prüfen — ändert sich oft)

| Provider | Kosten/Key | Stärken | Schwächen |
|---|---|---|---|
| Google Places (New) | Key + Abrechnung | beste Abdeckung, Öffnungsstatus, FUTURE_OPENING | max. 5 Reviews, max. 50 km Radius, nur Google-eigene Bewertungen |
| OpenStreetMap Overpass + Nominatim | kostenlos, kein Key | offene Daten, Tags wie `website`, `phone`, `opening_hours`, teils `start_date` | Datenqualität schwankt, keine Bewertungen, Rate-Limits beachten |
| Foursquare Places | Key, Free-Tier | gute POI-Daten, Kategorien | Abdeckung/Felder je Tarif unterschiedlich |
| HERE / TomTom / Geoapify | Key | Geocoding + POI-Suche, teils günstiger | weniger Details/Reviews |
| Yelp Fusion | Key | Reviews | schwach in DACH, wenige Reviews pro Call |
| SERP-/Scraping-Dienste (SerpApi, Outscraper, Apify) | bezahlt | liefern u. a. Maps-Daten inkl. mehr Reviews | ToS/Recht prüfen, Kosten pro Abfrage |
| Branchenverzeichnisse (Gelbe Seiten etc.) | variiert | lokale Tiefe | meist kein sauberes API |

Empfehlung für "nicht Google": **OSM Overpass als Erst-Provider** (kein Key, kostenlos), Google später optional.
Mehrere Provider parallel: `PROVIDERS = [OsmProvider(), GoogleProvider()]` → Ergebnisse mergen (Dedup nach Name+Adresse-Normalisierung
oder Koordinaten-Nähe), sonst entstehen Dubletten zwischen Quellen.

### 3.3 Was Provider-Grenzen für das Design bedeuten (Lehren aus dem Google-Bau)

- **Reviews limitiert** → Erkennungslogik darf sich nie NUR auf Reviews stützen; Website-HTML ist die verlässlichere Quelle.
- **Radius limitiert** (Google 50 km) → `max_radius_km` im Provider deklarieren, **serverseitig klemmen** (`min(radius, max)`), UI-Optionen daran ausrichten.
- **Kein "Profil erstellt am"-Datum** bei Google → "Neu" nur schätzbar. Bei OSM ggf. `start_date`-Tag nutzen.
- **Kein Feld "hat Buchen-Button"** → nur indirekt über Erkennung des Buchungsanbieters (Domain im HTML).
- **Konkurrenzsystem ist kein Provider-Feld** → immer erst suchen, dann selbst anreichern, dann filtern. Man kann den Provider nicht danach fragen.

---

## 4. Datenmodell (SQLite, exakt)

```sql
CREATE TABLE leads (
  place_id TEXT PRIMARY KEY,           -- RawPlace.id
  name TEXT, address TEXT, phone TEXT, website TEXT,
  rating REAL, rating_count INTEGER,
  business_status TEXT, open_now INTEGER,
  category_query TEXT, region_query TEXT,
  likely_new INTEGER,
  opening_status TEXT,                 -- 'Bald eröffnend' | 'Neu eröffnet' | 'Etabliert'
  opening_date TEXT,                   -- 'TT.MM.JJJJ' | 'MM.JJJJ' | 'JJJJ' | ''
  competitor_system TEXT,              -- '' = keins erkannt
  pain_points TEXT,                    -- ', '-getrennt
  score TEXT,                          -- Legacy-Ampel 'Heiss'|'Mittel'|'Niedrig'
  chain_flag INTEGER,
  first_seen TEXT,                     -- 'YYYY-MM-DD HH:MM:SS' (CET), sortierbar
  icp_score INTEGER, icp_tier TEXT,    -- 0..100, 'A'|'B'|'C'
  status TEXT DEFAULT 'Neu',           -- Neu|Kontaktiert|Termin gebucht|Nicht interessant|Kein Fit
  notes TEXT DEFAULT '',
  hidden INTEGER DEFAULT 0,            -- 1 = Tabelle "Exportiert"
  hidden_at TEXT
);

CREATE TABLE watched_searches (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  region TEXT, category TEXT, count INTEGER,
  radius_km REAL DEFAULT 0,
  created_at TEXT,
  UNIQUE(region, category)             -- gleiche Kombination überschreibt count/radius
);

CREATE TABLE action_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  action_type TEXT,                    -- search|sync|hide|unhide|bulk_hide|export|status_change|undo
  description TEXT,
  payload TEXT,                        -- JSON: [{"place_id":..., "previous": {feld: wert,...}}]
  undoable INTEGER DEFAULT 0,
  undone INTEGER DEFAULT 0,
  created_at TEXT
);
```

**Migrationen:** `init_db()` macht `CREATE TABLE IF NOT EXISTS`, danach `_migrate_add_columns()`:
`PRAGMA table_info(<tabelle>)` lesen, fehlende Spalten per `ALTER TABLE ... ADD COLUMN` nachrüsten. So überleben alte DBs jedes Update.
Gilt für **beide** Tabellen (leads UND watched_searches — das wurde einmal vergessen).

**Regel:** Insert nur, wenn `place_id` noch nicht existiert (`SELECT 1` vorher). Nie überschreiben. Bestehende Leads werden nicht neu bewertet
(bewusste Entscheidung: manuelle Status/Notizen dürfen nie durch Sync verloren gehen).

---

## 5. Pipeline (Reihenfolge ist wichtig)

```
run_search(regions[], category, count, radius_km):
  radius_km = min(radius_km, provider.max_radius_km)
  für jede region einzeln:                       # Radius gilt pro Ort, nicht global
      center = provider.geocode(region) if radius_km>0 else None
      raw = provider.search(category, region, count, center, radius_km)
      leads = [enrich(p) for p in raw]
      finalize(leads)                            # Ketten-Flag DANN Score
      new_ids += db.upsert_leads(leads)          # liefert nur die wirklich neuen IDs
      db.remember_search(region, category, count, radius_km)
  db.log_action('search', "Suche 'X' in A, B, Umkreis N km: F Treffer, M neu")
  return {found, new, new_place_ids, errors[]}   # Teilfehler pro Region sammeln, nicht abbrechen
```

`enrich(place)`:
1. `review_texts = provider.reviews(id)` (max. was der Provider hergibt)
2. `html = fetch_website_html(website)` — `requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})`, nur HTTP 200, lowercased; Fehler → `""`.
3. Signale berechnen (Abschnitt 6).
4. `first_seen = now_cet_sortable()`.
5. Dict im DB-Format zurückgeben, `icp_score=0, icp_tier=""` (kommt erst in `finalize`).

`finalize(leads)`: **erst** `flag_chains(leads)`, **dann** je Lead `compute_score(...)` — der Score braucht `chain_flag`.

`sync`: `for w in watched_searches: dieselbe Pipeline mit gespeichertem count+radius`. Rückgabe wie Suche, plus `synced_searches`.
Dauer: ca. 8 s pro gemerkter Suche (Reviews- + Website-Abrufe dominieren). Bei vielen Suchen → Job im Hintergrund/Queue (siehe Abschnitt 14).

---

## 6. Erkennung (Detectors) — exakte Logik

### 6.1 Konkurrenz-/Buchungssystem
Haystack = `website_url.lower() + " " + website_html + " " + " ".join(review_texts).lower()`.
Für jedes System in Config-Reihenfolge: wenn irgendeine Signatur (Substring) im Haystack → `return systemname` (erster Treffer gewinnt). Sonst `""`.
Signaturen sind **Domains** (`fresha.com`) und markante Phrasen (`powered by fresha`). Nur Markennamen ohne Domain (`"treatwell"` im Fließtext)
werden bewusst NICHT gematcht (Fehlalarme) — wenn gewünscht, als zweite, schwächere Stufe ergänzen.
Erkennung ist eine Heuristik: verpasst Systeme, die weder verlinkt noch in den abrufbaren Reviews erwähnt sind.

### 6.2 Pain-Points (Regex auf lowercased Review-Texte)
Dict `label -> [regex,...]`, pro Label reicht ein Treffer. Ausgabe = Liste der Labels.
Reihenfolge/Beispiele: siehe Config (Abschnitt 13). Umlaute immer doppelt abdecken: `(ü|ue)`, `(ä|ae)`.

### 6.3 Öffnungsstatus
```
business_status == "FUTURE_OPENING"                       -> "Bald eröffnend"
business_status == "OPERATIONAL" and rating_count < 5      -> "Neu eröffnet"     (Schätzung!)
sonst                                                      -> "Etabliert"
```
`opening_date` formatieren: Tag+Monat+Jahr -> `TT.MM.JJJJ`; nur Monat+Jahr -> `MM.JJJJ`; nur Jahr -> `JJJJ`; sonst `""`.
Legacy-Ampel `score`: kein Konkurrent & neu -> "Heiss"; kein Konkurrent -> "Mittel"; sonst "Niedrig".

### 6.4 Filialketten
`normalize_name`: lowercase → Rechtsformen/Füllwörter entfernen (`gmbh|ug|e.k.|inh.|filiale|standort`) → alle Ziffern raus →
alles außer a–z und Leerraum raus → Whitespace normalisieren. Gruppiere alle Leads **des aktuellen Batches** nach diesem Key.
Gruppengröße **3 bis 9** → alle in der Gruppe `chain_flag=1`. (Größer = Konzern, uninteressant; kleiner = Einzelbetrieb.)

---

## 7. Scoring (exakt, additiv, gedeckelt)

```
score  = category_weight[category]  (Default 15 für unbekannte Kategorien)    # max 30
score += 25 wenn competitor == ""                                              # Kaufsignal
score += 20 wenn rating_count >= 20, sonst 10 wenn >= 3                        # Volumen-Proxy
score += 15 wenn chain_flag                                                    # mehr Umsatz pro Deal
score += 10 wenn pain_points nicht leer                                        # Anruf-Aufhänger
score += opening_bonus[opening_status]   ("Bald eröffnend": 20, "Neu eröffnet": 15, "Etabliert": 0)
score = min(score, 100)
tier = "A" wenn score >= 65, "B" wenn >= 40, sonst "C"
```
Semantik in der UI: **höher = besser**, 100 % = perfekt, sofort anrufen. Tier A = **grün**, B = gelb, C = rot (klassische Ampel).
Gewichte/Schwellen liegen in der Config — das ist der wichtigste Hebel und sollte an echten Abschlüssen kalibriert werden.

---

## 8. HTTP-API (exakt)

| Route | Body/Query | Antwort |
|---|---|---|
| `GET /` | – | HTML, Kategorien fürs Datalist |
| `POST /api/search` | `{region:"A, B", category, count, radius_km}` | `{found, new, new_place_ids[], errors[]}` — Fehler nur wenn ALLES fehlschlägt (HTTP 502) |
| `POST /api/sync` | – | `{synced_searches, new, new_place_ids[], errors[]}`; 400 wenn keine gemerkten Suchen |
| `GET /api/leads` | optional Filter | **alle** Leads inkl. `hidden` (Filtern/Einteilen macht das Frontend) |
| `PATCH /api/leads/<id>` | `{status?, notes?, hidden?}` | `{ok:true}`; 404 wenn unbekannt. Loggt hide/unhide/status_change (undoable) |
| `POST /api/leads/hide-before` | `{date:"YYYY-MM-DD"}` | `{hidden:n, log_id}` — blendet alle mit `date(first_seen) <= date` aus |
| `GET /api/export?format=csv|xlsx|hubspot&hot_only=0` | – | Datei-Download; exportiert nur NICHT-ausgeblendete, blendet sie danach aus + loggt (undoable) |
| `GET /api/logs?limit=50` | – | neueste zuerst |
| `POST /api/logs/<id>/undo` | – | `{ok, count}`; 400 wenn nicht undoable/schon undone |

API-Key: Header `X-Api-Key` (aus UI-Feld) **oder** Env-Variable. UI blendet das Key-Feld aus, wenn die Env-Variable gesetzt ist.

---

## 9. Log, Undo, Redo (Design)

- Jede ändernde Aktion schreibt vorher-Zustand in `payload`: `[{"place_id": X, "previous": {"hidden":0,"hidden_at":null}}]`.
- `undo(log_id)`: prüft `undoable=1 AND undone=0`; liest für jedes Payload-Item den **aktuellen** Wert derselben Felder (→ `redo_payload`),
  schreibt dann die `previous`-Werte zurück, setzt `undone=1`, gibt `redo_payload` zurück.
- Die Route schreibt daraufhin einen **neuen** Log-Eintrag `undo` mit `payload=redo_payload`, `undoable=1`.
  → Undo vom Undo = Redo. Kette beliebig lang, Historie bleibt vollständig.
- Spaltennamen in `SET a=?,b=?` kommen ausschließlich aus eigenem Code (nie aus User-Input) → kein SQL-Injection-Risiko.
- Such-/Sync-Einträge sind **nicht** undoable (würde echte Fremddaten löschen).
- Bulk-Aktionen (Export, Hide-before) speichern pro Lead einen Payload-Eintrag → ein Klick macht 50+ Leads rückgängig.
- Bekannte Grenze: Wird ein älterer Eintrag rückgängig gemacht, obwohl derselbe Lead danach nochmals geändert wurde, gewinnt der ältere Zustand.

---

## 10. Export

`DISPLAY_COLUMNS` = Liste `(feld, überschrift)`; berechnete Felder werden vor dem Schreiben in jede Zeile eingefügt:
`google_search_url` (bzw. Provider-Deeplink) und `first_seen_display` (`HH:MM - TT-MM-JJJJ`).
- **CSV**: Trenner `;`, Encoding `utf-8-sig` (Excel-Umlaute).
- **XLSX** (openpyxl): Kopfzeile fett, Tier-Zelle eingefärbt, Pain-Points-Zelle gelb, Spaltenbreite = max Länge+2 (Deckel 45).
- **HubSpot-CSV**: Spalten `Company name, Phone Number, Website URL, <Profil-Link>, Street Address, ICP Score, ICP Tier, Erkanntes Konkurrenzsystem, Status, Notiz`;
  Notiz = `" | "`-Verkettung aus Eröffnungsstatus(+Datum), "Teil einer Filialkette", "Review Pain-Points: …", eigene Notiz.
- Dateiname `basename_YYYYMMDD_HHMMSS.ext`.

---

## 11. Frontend (Vanilla JS, eine Seite)

**Seitenaufbau von oben:** Toast (fixed, 3 s) → API-Key-Box (nur ohne Env-Key) → Aktivitäts-Log (`<details>`, zugeklappt, Kopfzeile zeigt
"Aktivitäts-Log (N)" + darunter letzten Eintrag) → Suche → Aufräumen (`<details>`, zu) → Neu → Alt → Exportiert (alle `<details>`).

**Suche:** Region-Textfeld (Komma = mehrere), Umkreis-Select (`0 = ganzes Gebiet`, 5, 15, 50 …, `eigener Wert`→Zahlenfeld, geklemmt auf Provider-Maximum),
Kategorie (Textfeld + `<datalist>` aus Config), Anzahl (1–60), Button Suchen, Button Sync, Statuszeile.

**Drei Tabellen, gleiche 17 Spalten:**
Name, Adresse, Telefon, Website, Google-Profil, ICP-Score (%), Tier, System, # Reviews, Offen, Eröffnung, Kette?, Pain-Points, Status (Dropdown, speichert sofort), Notiz (Input, speichert bei blur), In-DB-seit (`HH:MM - TT-MM-JJJJ`), HubSpot-Button.
- Zeilenfarbe nach Tier (A grün `#c9ecc9`, B gelb `#ffe0a3`, C rot `#ffb3b3`).
- **Einteilung** (`renderAll`): `hidden=1` → Exportiert; sonst ID in `newOnlyIds` (Ergebnis der **letzten** Suche/Sync, wird jedes Mal komplett ersetzt) → Neu; sonst Alt.
  → Frühere "Neu"-Leads rutschen automatisch nach Alt, sobald neu gesucht wird. `newOnlyIds` lebt nur im Browser (Reload = alles in Alt).
- **Zweite Kopfzeile = Spaltenfilter**, per JS aus einer Config-Liste erzeugt (`COLUMN_FILTERS`, ein Eintrag pro Spalte, gleiche Reihenfolge wie `<th>`):
  `text` (enthält, case-insensitive), `select` (exakter Vergleich über `get(lead)`), `numMin` (>=), `none`.
  Beispiele: Website/Offen/Kette → select ja/nein; System → select aller Systeme + "ohne" (`competitor_system || "ohne"`); Eröffnung → Default "Etabliert".
- **Volltextsuche** pro Tabelle: ein Input über der Tabelle, sucht in Name, Adresse, Telefon, Website, System, Pain-Points, Notiz, Status, Eröffnung, Tier, Region, Kategorie.
- Filterzustand je Tabelle getrennt (`filterState = {neu, alt, exported}`).
- **Sortierung** nur für Alt: Select (ICP-Score, # Reviews, Name, Zuerst gefunden) + Richtungs-Button. Sortierwert für Zeit ist der rohe ISO-String (lexikografisch = chronologisch), **angezeigt** wird das schöne Format. Neu/Exportiert: fix nach ICP-Score absteigend.
- Zählung im Titel: `(gefiltert von gesamt)`.
- HubSpot-Button togglet `hidden` (Label "In HubSpot" ↔ "Einblenden"), rendert neu, lädt Log neu, zeigt Toast.

**Log-UI:** Eintrag = Zeit + Text + (wenn undoable && !undone) Button "Rückgängig". Nach Undo `loadLeads()` + `loadLogs()`.

**Tabellen-Kopf:** `<details class="table-section">` mit eigenem ▶/▼ per CSS `::before` (Default-Marker ausblenden).

---

## 12. Zeit & Format

- Serverseitig `zoneinfo.ZoneInfo("Europe/Berlin")` (kein UTC, kein `datetime('now')` von SQLite — das ist UTC).
- Speichern: `YYYY-MM-DD HH:MM:SS`. Anzeigen: `HH:MM - TT-MM-JJJJ` (JS-Regex `^(\d{4})-(\d{2})-(\d{2})(?: (\d{2}):(\d{2}))?`; Altdaten ohne Uhrzeit → `TT-MM-JJJJ`).
- Nur-Datum als Sortierschlüssel war ein Fehler (alle Leads eines Tages gleich → Sortierung wirkt kaputt). Immer Uhrzeit speichern.
- SQL `date(first_seen)` funktioniert mit dem Format weiter (für Hide-before).

---

## 13. Config (`config.py`) — das ist die einzige Datei, die du für neue Branchen anfasst

```python
CATEGORIES = ["Kosmetikstudio", "Friseur", "Nagelstudio", "Botox / Medical Beauty", "Bleaching-Zentrum",
              "Wellness / Spa", "Brautmode", "Physiotherapie", "Tierarzt / Hundesalon", "Tattoo-Studio", "Massage-Praxis"]

CATEGORY_WEIGHTS = {"Botox / Medical Beauty":30, "Brautmode":30, "Wellness / Spa":25, "Bleaching-Zentrum":22,
                    "Kosmetikstudio":22, "Physiotherapie":20, "Nagelstudio":18, "Friseur":18, "Massage-Praxis":18,
                    "Tattoo-Studio":15, "Tierarzt / Hundesalon":15}
DEFAULT_CATEGORY_WEIGHT = 15

# Erkannte Systeme = "Konkurrenz". Reihenfolge = Priorität. Signaturen: Substrings, lowercase.
COMPETITOR_SIGNATURES = {
  "Fresha": ["fresha.com","fresha.de","book with fresha","powered by fresha"],
  "Treatwell": ["treatwell.de","treatwell.com","treatwell.at","treatwell.ch"],
  "Planity": ["planity.com"], "SumUp": ["sumup.com","sumup.de","pay.sumup"], "Calendly": ["calendly.com"],
  "Booksy": ["booksy.com"], "Salonized": ["salonized.com"],
  "Beautinda": ["beautinda.de","beautinda.com","book with beautinda","powered by beautinda"],
  "Shortcuts": ["shortcuts.com"], "Timify": ["timify.com"], "Phorest": ["phorest.com"],
  "Terminland": ["terminland.de","terminland.com"], "Salonkee": ["salonkee.de","salonkee.lu","salonkee.com"],
  "Timely": ["gettimely.com"], "Vagaro": ["vagaro.com"],
  "<EIGENE FIRMA> (bereits Kunde)": ["<deine-buchungs-domains>"],   # eigene Kunden erkennen, damit sie nicht angerufen werden
}

PAIN_POINT_PATTERNS = {
  "Schwer erreichbar": [r"schwer erreichbar", r"nicht erreichbar", r"niemand (geht|nimmt) ans telefon",
                        r"kein(e)? r(ü|ue)ckruf", r"nie(mand)? erreicht", r"telefonisch nicht"],
  "Terminvergabe kompliziert": [r"termin.{0,15}(schwierig|kompliziert|umst(ä|ae)ndlich)",
                        r"lange (auf einen termin )?gewartet", r"keine termine (frei|verf(ü|ue)gbar)", r"schwer einen termin"],
  "Keine Rückmeldung": [r"keine (r(ü|ue)ckmeldung|antwort)", r"nicht (geantwortet|zur(ü|ue)ckgemeldet)", r"nachricht.{0,15}ignoriert"],
}

SCORING = {
  "no_competitor": 25, "volume_high": (20, 20), "volume_mid": (3, 10),   # (ab rating_count, Punkte)
  "chain": 15, "pain_point": 10,
  "opening_bonus": {"Bald eröffnend": 20, "Neu eröffnet": 15, "Etabliert": 0},
  "tier_a": 65, "tier_b": 40,
}
NEW_BUSINESS_MAX_REVIEWS = 5        # "Neu eröffnet" wenn OPERATIONAL und darunter
CHAIN_SIZE = (3, 9)
STATUS_OPTIONS = ["Neu","Kontaktiert","Termin gebucht","Nicht interessant","Kein Fit"]
```

**Neue Branche = nur diese Datei ändern.** Beispiele: Zahnärzte (Signaturen: Doctolib, Jameda, Samedi), Restaurants (OpenTable, Quandoo, TheFork),
Handwerker (kein Buchungssystem → Signal "hat Online-Terminformular nicht"), Fitnessstudios (Magicline, Eversports), Autowerkstätten.
Gewichte pro Kategorie an Ticketgröße/Abschlussquote der Branche anpassen.

---

## 14. Skalierung in andere Richtungen

- **Andere Datenquelle:** neuen Provider implementieren (Abschnitt 3), in `PROVIDERS` eintragen, UI-Select "Quelle" ergänzen. Rest unverändert.
- **Andere Signale statt "Konkurrenzsystem":** `detect_competitor` ist ein Spezialfall von `detect_tech(html, signatures)`. Genauso möglich:
  "nutzt WordPress/Shopify", "hat Chat-Widget", "hat Google Tag Manager", "hat Impressum-Mail" → jeweils ein Detector + ein Gewicht in `SCORING`.
- **Kontaktdaten anreichern:** Impressum-Seite crawlen (E-Mail, Inhaber), Hunter/Apollo-artige Dienste als zusätzlicher Enrichment-Schritt.
- **Große Läufe:** Suche/Sync in Hintergrund-Thread oder Job-Queue (RQ/Celery/`concurrent.futures`), Fortschritt über Polling-Route,
  Enrichment parallelisieren (`ThreadPoolExecutor`, 5–10 Worker, Rate-Limit pro Host).
- **Mehrere Nutzer/Team:** SQLite → Postgres, `owner_id`-Spalte, Login. Log-Tabelle bleibt strukturgleich.
- **Automatisierung mit Agenten:** tägliche geplante Läufe (Sync + Morgen-Digest der neuen Tier-A-Leads), Outreach-Entwurf pro Lead
  aus Signalen (kein Buchungssystem + Pain-Point → Gesprächseinstieg), Wiedervorlage-Erinnerung für "Kontaktiert" ohne Follow-up.
  Agenten dürfen lesen/entwerfen; Versand/Statusänderung nur nach menschlicher Freigabe.
- **CRM-Anbindung statt CSV:** direkter HubSpot-/Pipedrive-API-Push, `hubspot_id` pro Lead speichern → "Exportiert" wird echte Sync-Info.
- **Mehr Länder:** Signaturen um lokale Anbieter erweitern, Regex-Patterns pro Sprache (`PAIN_POINT_PATTERNS[lang]`), Zeitzone konfigurierbar.

---

## 15. Phasen-Prompts (nacheinander in Claude Code einfügen)

**Phase 1 — Gerüst + Datenmodell**
> Baue eine lokale Flask-App (Python 3.9+, nur flask, requests, openpyxl) mit Ordnerstruktur laut Abschnitt 2 von BUILD_SPEC.md.
> Implementiere `db.py` komplett nach Abschnitt 4 inkl. `init_db()`, Migration für beide Tabellen, `upsert_leads()` (gibt Liste neuer IDs zurück),
> `get_all_leads(include_hidden)`, `get_lead`, `update_lead(status, notes, hidden)`, `hide_leads(ids)` (gibt previous-Payload zurück),
> `hide_leads_before(date)`, `remember_search`, `get_watched_searches`, `log_action`, `get_logs`, `undo_log` (mit redo_payload). Zeiten via Europe/Berlin.
> Abnahme: Python-Skript, das Leads einfügt, versteckt, undo/redo macht und die Zustände asserted.

**Phase 2 — Detectors + Scoring (reine Funktionen) + Config**
> Lege `config.py` nach Abschnitt 13 an. Implementiere `detectors.py` (competitor, pain_points, opening_status, format_opening_date, flag_chains, legacy_score)
> und `scoring.py` (compute_score) exakt nach Abschnitt 6–7. Schreibe pytest-Tests mit mind. je 3 Fällen pro Funktion (inkl. Kette mit 2/3/9/10 Gleichnamigen,
> Score-Deckel bei 100, Tier-Grenzen 64/65/39/40).
> Abnahme: `pytest` grün.

**Phase 3 — Provider-Interface + erster Provider**
> Implementiere `providers/base.py` (Provider, RawPlace) nach Abschnitt 3.1 und `providers/<GEWÄHLTER PROVIDER>.py`. Normalisiere Status/IDs, deklariere `max_radius_km` und `max_reviews`.
> Baue `pipeline.py` nach Abschnitt 5 (run_search, run_sync, enrich, finalize) mit Teilfehler-Sammlung pro Region und Radius-Klemmung.
> Abnahme: CLI-Test `python -m pipeline "Berlin, Wien" "Friseur" 5 15` speichert Leads, zweiter Lauf fügt 0 neue hinzu.

**Phase 4 — HTTP-API**
> Implementiere `app.py` mit allen Routen aus Abschnitt 8 inklusive Logging/Undo-Verhalten aus Abschnitt 9 und Export-Auto-Hide. Keine Logik in den Routen.
> Abnahme: curl-Skript: search → leads → PATCH hidden → logs → undo → undo(undo) → export csv; jeweils Zustand prüfen.

**Phase 5 — Exporte**
> Implementiere `exports.py` nach Abschnitt 10 (CSV `;` utf-8-sig, XLSX mit Färbung, HubSpot-CSV, berechnete Felder). Abnahme: Dateien öffnen sich in Excel mit korrekten Umlauten.

**Phase 6 — Frontend**
> Baue `templates/index.html`, `static/app.js`, `static/style.css` exakt nach Abschnitt 11: drei `<details>`-Tabellen Neu/Alt/Exportiert, JS-generierte Filterzeile aus `COLUMN_FILTERS`,
> Volltextsuche je Tabelle, Sortierung nur Alt, Toast, Aktivitäts-Log mit Vorschau und Undo-Buttons, Umkreis-Select mit Custom-Feld, Aufräumen-Bereich mit Datum.
> Kein Framework, kein Build. Abnahme: alle Element-IDs aus app.js existieren im HTML (Skript-Check), Klammern-Balance-Check, manueller Klicktest.

**Phase 7 — Härtung**
> Füge hinzu: Env-Key-Handling, `.gitignore` (leads.db, __pycache__, .DS_Store), README mit Startbefehl, Fehlermeldungen in Deutsch,
> Timeouts überall, kein Crash bei fehlender Website/Review-Antwort. Stelle sicher, dass Templates nach Änderungen neu geladen werden
> (Flask ohne Debug cached Templates → Server neu starten oder `TEMPLATES_AUTO_RELOAD=True`).

**Phase 8 (optional) — Anderer Provider / andere Branche**
> Implementiere zusätzlich `providers/osm_overpass.py`. Passe nur `config.py` für die Branche <X> an. Ändere sonst nichts.

---

## 16. Lehren aus dem Bau (Fehler, die du dir sparen kannst)

1. Datum ohne Uhrzeit als Sortierschlüssel → Sortierung "geht nicht". Immer Zeitstempel.
2. Migration nur für eine Tabelle geschrieben → neue Spalte in `watched_searches` fehlte auf Bestands-DB. Immer alle Tabellen migrieren.
3. Flask ohne Debug cached Templates; nach HTML-Änderung Server **neu starten**, sonst sieht man nichts. Alten Prozess auf dem Port sicher beenden (`lsof -ti :PORT | xargs kill`).
4. Annahme "Provider liefert alle Reviews" war falsch (Google: 5). Erkennungslogik so bauen, dass sie mit wenig Text funktioniert.
5. Annahme "beliebiger Radius" war falsch (Google: max. 50 km, sonst HTTP 400). Provider-Grenzen früh in einem Testaufruf prüfen.
6. Toolbar-Filter nur für eine Tabelle gebaut → später Umbau auf generische Filterzeile für alle. Direkt generisch bauen.
7. `datetime('now')` in SQLite ist UTC — Log-Zeiten waren 2 h falsch. Zeit immer in Python erzeugen.
8. Test-Suchen füllen die Produktiv-DB. Für Tests eigene DB-Datei (`DB_PATH` per Env) benutzen.
9. Export, der still ausblendet, braucht Undo — sonst löscht ein versehentlicher Klick die Arbeitsansicht.
10. Öffentliches Repo: `leads.db` (echte Firmendaten) und API-Keys niemals committen; Key nur aus Env.

---

## 17. Abnahme-Checkliste (Gesamtsystem)

- [ ] Suche mit 2 Orten + Radius liefert Treffer aus beiden, Radius >Max wird geklemmt
- [ ] Gleiche Suche zweimal → 0 neue, keine Dubletten
- [ ] Sync durchläuft alle gemerkten Suchen mit ihrem Radius
- [ ] Score/Tier nach Abschnitt 7 nachrechenbar (Stichprobe von 5 Leads)
- [ ] Konkurrenz aus HTML erkannt (Testseite mit `fresha.com`-Link)
- [ ] Neu/Alt/Exportiert-Einteilung; neue Suche verschiebt vorherige Neu-Leads nach Alt
- [ ] Spaltenfilter + Volltextsuche in allen drei Tabellen
- [ ] Export blendet aus und ist per Undo komplett umkehrbar; Redo funktioniert
- [ ] Zeiten CET, Format `HH:MM - TT-MM-JJJJ`, Sortierung nach "Zuerst gefunden" ändert die Reihenfolge sichtbar
- [ ] Kein API-Key/keine DB im Repo
