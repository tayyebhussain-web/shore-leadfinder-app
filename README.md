# Shore Lead Finder

**Findet Unternehmen auf Google Maps, erkennt automatisch, welche noch kein Buchungssystem nutzen, und sagt dir, wen du zuerst anrufen solltest.**

Ein lokales Vertriebstool für die Kaltakquise: Du gibst Ort und Branche ein, das Tool holt passende Betriebe, prüft ihre Website und Bewertungen und sortiert sie nach Anruf-Priorität von 0 bis 100 %. Alles wird dauerhaft gespeichert, Duplikate sind ausgeschlossen, und jede Änderung lässt sich rückgängig machen.

> Entwickelt für den Vertrieb von Buchungs- und Zahlungssoftware an Beauty-, Wellness- und Gesundheitsbetriebe im DACH-Raum. Die Branche ist eine Konfiguration, kein Fundament: Das Prinzip funktioniert für jede Zielgruppe.

---

## Was das Tool kann

### Suchen
- **Mehrere Orte auf einmal**, kommagetrennt: `Berlin, München, Wien, Zürich`
- **Stadt, Bezirk oder PLZ** möglich, z. B. `Charlottenburg Berlin` oder `10115 Berlin`
- **Umkreis pro Ort**: 5, 15, 50 km oder eigener Wert (Maximum 50 km, das ist ein Limit von Google)
- **Branche frei wählbar** (11 Vorschläge hinterlegt, z. B. Friseur, Nagelstudio, Kosmetikstudio, Physiotherapie)
- **Sync-Button**: wiederholt alle bisherigen Suchen und findet nur die Betriebe, die neu dazugekommen sind, zum Beispiel frisch eröffnete

### Erkennen (das eigentliche Kaufsignal)
Zu jedem Betrieb prüft das Tool die Startseite und die verfügbaren Bewertungen und zeigt:

| Signal | Bedeutung |
|---|---|
| **Genutztes Buchungssystem** | Erkennt 23 Anbieter, u. a. Treatwell, Fresha, Planity, Booksy, Timify, Phorest sowie Doctolib, Dr. Flex und Jameda für Praxen. Mehrere Systeme pro Betrieb werden alle angezeigt. Kein System erkannt = interessanter Lead. |
| **Eröffnungsstatus** | *Bald eröffnend* (von Google als künftige Eröffnung geführt), *Neu eröffnet* (aktiv, aber unter 5 Bewertungen, eine Schätzung), *Etabliert* |
| **Kette** | Mindestens 2 bekannte Standorte derselben Marke, erkannt an gleichem Markennamen oder gleicher Website. Die Spalte zeigt z. B. **Ja (5)**. Mehr Umsatzpotenzial pro Abschluss |
| **Pain-Points** | Kunden schreiben in Bewertungen "schwer erreichbar", "Termin kompliziert", "keine Rückmeldung": ein konkreter Gesprächseinstieg |

### Bewerten: der ICP-Score
Jeder Betrieb bekommt einen Wert von **0 bis 100 %**. Höher ist immer besser, 100 % heißt: perfekter Fit, sofort anrufen.

| Baustein | Punkte |
|---|---|
| Branchen-Fit (konfigurierbar) | bis 30 |
| **Kein** Buchungssystem erkannt | 25 |
| Bewertungsvolumen als Kundenvolumen-Indikator | 10 bis 20 |
| Kette (ab 2 Standorten) | 15 |
| Pain-Point in Bewertungen | 10 |
| Bald eröffnend / Neu eröffnet | 20 / 15 |

| Tier | Farbe | Score | Bedeutung |
|---|---|---|---|
| **A** | grün | ab 65 % | heiß, zuerst anrufen |
| **B** | gelb | 40 bis 64 % | mittel |
| **C** | rot | unter 40 % | niedrige Priorität |

### Arbeiten: drei Tabellen statt einer Liste

```
NEU          Alles aus der letzten Suche oder dem letzten Sync
ALT          Alles Bekannte, das noch nicht erledigt ist
EXPORTIERT   Alles, was du schon in HubSpot hast oder exportiert hast
```

- Jede Tabelle ist **auf- und zuklappbar**.
- **Spaltenfilter** unter jeder Kopfzeile (Text, Auswahl, Mindestwert) und eine **Volltextsuche** über Name, Adresse, Telefon, Notiz und mehr, in jeder Tabelle einzeln.
- **Sortieren** nach Score, Bewertungen, Name oder Fund-Zeitpunkt, für "Neu" und "Alt" getrennt. Beide Tabellen haben dieselbe Leiste mit Sortierung, "Spalten zurücksetzen" und Export.
- **Spalten per Maus verschieben**: Überschrift anklicken, halten und ziehen, die Spalten rutschen live mit. Die Reihenfolge gilt für alle drei Tabellen und bleibt im Browser gespeichert. "Spalten zurücksetzen" stellt die Standardreihenfolge wieder her.
- Pro Betrieb: **Status** (Neu, Kontaktiert, Termin gebucht, Nicht interessant, Kein Fit) und **Notiz**, sofort gespeichert.
- Ein Klick auf **"In HubSpot"** verschiebt einen Betrieb nach *Exportiert*, "Einblenden" holt ihn zurück.
- **Aufräumen**: Alles bis zu einem Datum auf einmal nach *Exportiert* schieben, praktisch für den einmaligen Abgleich mit dem CRM.

### Exportieren
**CSV**, **Excel** (mit Farbmarkierung) und **HubSpot-Importliste**. Jede Tabelle exportiert genau die Leads, die in ihr gerade sichtbar sind (mit Suche, Filtern und Sortierung). Exportierte Betriebe wandern automatisch nach *Exportiert*, du exportierst nie zweimal dasselbe.

### Rückgängig machen
Das **Aktivitäts-Log** (oben, aufklappbar) protokolliert jede Änderung mit Uhrzeit (CET). Jede Änderung hat einen **"Rückgängig"-Button**, auch ein Massen-Export mit 50 Betrieben lässt sich mit einem Klick zurücknehmen. Auch das Zurücknehmen lässt sich zurücknehmen.

---

## Schnellstart

Voraussetzung: **Python 3.9 oder neuer** und ein **Google-API-Key** (einmalig einrichten, ca. 5 Minuten).

**1. Google-Key besorgen**
1. In der [Google Cloud Console](https://console.cloud.google.com) ein Projekt anlegen.
2. Unter *APIs & Services, Library* **"Places API (New)"** aktivieren.
3. Unter *Billing* eine Zahlungsmethode hinterlegen (Pflicht bei Google, Kosten selbst im Blick behalten).
4. Unter *Credentials* einen **API-Key** erstellen und auf "Places API (New)" beschränken.

**2. Installieren und starten**
```bash
git clone https://github.com/HussainTayyeb/shore-leadfinder-app.git
cd shore-leadfinder-app
python3 -m pip install -r requirements.txt

export GOOGLE_MAPS_API_KEY="dein-key"
python3 app.py
```
Dann im Browser öffnen: **http://127.0.0.1:5050**

Den Key kannst du alternativ oben im Browser eintragen (gilt nur für die laufende Sitzung, wird nicht gespeichert). Die Datenbank `leads.db` wird beim ersten Start automatisch angelegt und bleibt zwischen Neustarts erhalten.

---

## Ehrlich gesagt: Grenzen

- **Google liefert nur 5 Bewertungen pro Betrieb.** Die Erkennung eines Buchungssystems stützt sich deshalb vor allem auf die Website, nicht auf Bewertungen.
- **Erkennung ist eine Heuristik.** Ein Buchungssystem wird nur gefunden, wenn sein Link auf der Startseite steht oder in einer der 5 Bewertungen erwähnt wird. Unterseiten werden nicht geladen.
- **"Neu eröffnet" ist eine Schätzung** (aktiv und unter 5 Bewertungen). Google gibt kein Eröffnungsdatum bereits eröffneter Betriebe heraus.
- **Maximal 50 km Umkreis**, das ist ein hartes Limit der Google-API.
- **Die Branchen-Gewichte im Score sind eine Annahme**, keine gemessenen Abschlusszahlen. Sie liegen in einer Konstante und sollten mit echten Deals abgeglichen werden.
- **Jeder Google-Aufruf kostet etwas.** Bei sehr großen Suchen oder häufigem Sync das Budget beobachten. Ein Sync mit 7 gespeicherten Suchen dauerte ca. 1 Minute.
- **Bekannte Kanten**: Die Excel-Tier-Farben sind gegenüber der Oberfläche vertauscht. Eine in die Website eingebaute eigene Buchung (ohne Anbieter-Link) wird nicht erkannt. Die vollständige Liste steht in `BUILD_GUIDE.txt`, Abschnitt 16.

---

## Aufbau

```
app.py            Web-Server und Schnittstellen (Flask)
lead_logic.py     Datenquelle, Erkennung, Score
db.py             Datenbank (SQLite), Log und Rückgängig-Logik
exports.py        CSV, Excel, HubSpot-Liste
templates/        Oberfläche (HTML)
static/           Oberfläche (JavaScript, CSS)
```

**Technik:** Python, Flask, SQLite, `requests`, `openpyxl`, reines JavaScript ohne Framework und ohne Build-Schritt.

## Datenquelle austauschbar

Google steckt nur in wenigen, klar benannten Stellen (Suche, Ortsauflösung, Bewertungen, Schlüsselverwaltung). Das Tool lässt sich auf eine andere Datenquelle umbauen, zum Beispiel OpenStreetMap, ohne die Erkennung, den Score oder die Oberfläche anzufassen. Die Branche (Kategorien, Gewichte, Anbieter-Signaturen) liegt in wenigen Konstanten.

## Dokumentation

| Datei | Inhalt |
|---|---|
| [`BUILD_GUIDE.txt`](BUILD_GUIDE.txt) | Jede Funktion, Route, Tabelle und jedes Ereignis im Detail, dazu die Austauschpunkte für andere Datenquellen |
| [`MASTER_PROMPT.txt`](MASTER_PROMPT.txt) | Fertige Prompts für Claude Code: komplett nachbauen oder die Datenquelle tauschen |
