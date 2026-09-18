# Shore Lead Finder — Setup (Web-App mit DB)

Lokale Web-App: du startest sie einmal auf deinem Rechner, öffnest sie im Browser,
und alle Suchen landen dauerhaft in einer lokalen Datenbank (`leads.db`, SQLite).
Der "Sync"-Button prüft alle bisher gesuchten Region+Kategorie-Kombinationen erneut
und fügt nur wirklich neue Treffer hinzu (z. B. frisch eröffnete Läden, die beim
letzten Mal noch nicht bei Google gelistet waren).

## 1. Google API-Key besorgen (einmalig, ca. 5 Min.)

1. https://console.cloud.google.com → neues Projekt anlegen (oder bestehendes nutzen).
2. **APIs & Services → Library** → "**Places API (New)**" suchen → **Enable**.
3. **Billing** → Zahlungsmethode hinterlegen (Pflicht für die API, Google gibt aktuell
   $200 Gratis-Guthaben/Monat — für ein paar hundert Suchen im Monat idR kostenlos,
   trotzdem selbst im Blick behalten).
4. **APIs & Services → Credentials → Create Credentials → API Key**.
5. Key anklicken → **Restrict Key** → auf "Places API (New)" beschränken.

## 2. Installation

```bash
cd shore_leadfinder_app
pip install -r requirements.txt
```

Python 3.9+ wird vorausgesetzt.

## 3. Starten

```bash
export GOOGLE_MAPS_API_KEY="dein-key-hier"
python3 app.py
```

Dann im Browser öffnen: **http://127.0.0.1:5050**

Wenn du die Umgebungsvariable nicht setzen willst, kannst du den Key auch direkt
oben im Browser-Fenster eintragen (wird nur für die laufende Session verwendet,
nirgendwo gespeichert).

## Bedienung

1. Region/Stadt + Kategorie eingeben (freie Eingabe, ICP-Kategorien werden als
   Vorschlagsliste angezeigt), Anzahl festlegen, **Suchen** klicken.
2. Ergebnisse landen direkt in der Tabelle unten und in der lokalen Datenbank.
3. Nächstes Mal einfach eine neue Region/Kategorie suchen, oder auf **Sync**
   klicken — das prüft *alle* bisher gesuchten Kombinationen erneut und holt nur
   neue Treffer nach (z. B. neu eröffnete Läden).
4. Filter "nur Heiß anzeigen", Sortierung nach Score/Bewertungen/Name/Datum.
5. Export als CSV, farbcodiertes Excel oder HubSpot-Importliste — exportiert
   immer die komplette (bzw. gefilterte) Datenbank, nicht nur den letzten Lauf.

Die Datenbank (`leads.db`) bleibt zwischen Neustarts erhalten — du kannst die App
schließen und morgen weitermachen, nichts geht verloren.

## ICP-Scoring & Qualifizierung (neu)

Jeder Lead bekommt zusätzlich zur Konkurrenz-Ampel einen **ICP-Score (0–100)** und ein
**Tier (A/B/C)**, damit du nicht nur siehst "kein System erkannt", sondern auch "lohnt
sich das überhaupt, hier anzurufen". Der Score setzt sich zusammen aus:

- Kategorie-Fit (bis 30 Punkte) — z. B. Botox/Medical Beauty und Brautmode aktuell höher
  gewichtet als Friseur/Nagelstudio, weil dort laut deinen bisherigen Pitches größere
  Warenkörbe/Anzahlungen eine Rolle spielen
- Kein Konkurrenzsystem erkannt (bis 25 Punkte) — das eigentliche Kaufsignal
- Bewertungsvolumen als Kundenvolumen-Proxy (bis 20 Punkte)
- Filialkette, 3–9 Standorte (bis 15 Punkte) — mehr MRR-Potenzial pro Deal
- Review-Pain-Point gefunden (bis 10 Punkte) — konkreter Gesprächsaufhänger

Tier A = 65+ (heiß), B = 40–64 (mittel), C = unter 40 (niedrig).

**Wichtig:** Die Kategorie-Gewichtung (`CATEGORY_WEIGHTS` oben in `lead_logic.py`) ist
eine Annahme von mir auf Basis dessen, was im Projekt zu Deal-Größen dokumentiert ist —
nicht durch echte Abschlusszahlen abgesichert. Wenn du nach ein paar Wochen siehst, dass
z. B. Nagelstudios schneller abschließen als Brautmode, einfach die Zahlen in der Datei
anpassen — das ist der Hebel mit dem größten Effekt auf die Priorisierung.

**Qualifizierung direkt in der Tabelle:** jeder Lead hat ein Status-Dropdown (Neu /
Kontaktiert / Termin gebucht / Nicht interessant / Kein Fit) und ein Notizfeld — beides
wird sofort beim Ändern gespeichert. Filter oben in der Tabelle nach Tier und Status.
Das ersetzt **nicht** HubSpot als CRM — Gedanke ist: hier grob vorqualifizieren und
filtern, dann die "Tier A + Status Termin gebucht"-Leads über den HubSpot-Export
rüberziehen, statt jeden rohen Google-Treffer einzeln in HubSpot zu pflegen.

## Was erkannt wird

- **Konkurrenzsystem**: Fresha, Treatwell, Planity, SumUp, Calendly, Booksy,
  Salonized, "bereits Shore-Kunde" — über Website-Inhalt + Reviewtext
- **Wahrscheinlich neu eröffnet**: Heuristik über wenige Bewertungen + Status
  "operativ" — **kein Beweis**, vor dem Anruf kurz gegenchecken
- **Review-Pain-Points**: schwer erreichbar, Terminvergabe kompliziert, keine
  Rückmeldung — basiert auf den maximal 5 aktuellsten Reviews, die die Places
  API liefert (keine volle Reviewhistorie verfügbar)
- **Score-Ampel**: Heiß (kein System + neu/wenig Bewertungen), Mittel (kein
  System, etabliert), Niedrig (nutzt bereits ein Konkurrenzsystem)
- **Filialkette**: 3–9 namensähnliche Treffer innerhalb eines Suchlaufs

## Grenzen (bewusst nicht schöngeredet)

- Neu-Erkennung ist ein Proxy ohne offizielles Eröffnungsdatum.
- Konkurrenzsystem-Erkennung braucht eine Website oder einen Hinweis im
  Reviewtext — ohne beides keine Aussage möglich.
- Jeder Google-Places-Call kostet etwas vom Guthaben — bei sehr großen
  Suchen/häufigem Sync das Budget im Blick behalten.
- Läuft lokal bei dir, nicht als gehosteter Dienst — Key bleibt privat, aber
  du musst die App selbst laufen lassen, wenn du sie nutzen willst.
