#!/usr/bin/env python3
"""
Shore Lead Finder - lokale Web-App mit persistenter Datenbank.

Start:
    export GOOGLE_MAPS_API_KEY="dein-key"
    python3 app.py
    -> oeffnet auf http://127.0.0.1:5050

Siehe README.md fuer die einmalige Google-API-Key-Einrichtung.
"""

import os
from concurrent.futures import ThreadPoolExecutor

from flask import Flask, jsonify, render_template, request, send_file
import io

import db
import exports
import lead_logic

app = Flask(__name__)
db.init_db()


def get_api_key():
    return request.headers.get("X-Api-Key") or os.environ.get("GOOGLE_MAPS_API_KEY")


def annotate_chains(rows):
    """Ergaenzt chain_count (Anzahl bekannter Standorte der Marke) und setzt chain_flag daraus. Gezaehlt wird
    ueber die ganze Datenbank inklusive ausgeblendeter Leads, daher immer aktuell."""
    sizes = lead_logic.chain_sizes(db.get_all_leads(include_hidden=True))
    for row in rows:
        count = sizes.get(row["place_id"], 1)
        row["chain_count"] = count
        row["chain_flag"] = int(count >= 2)
    return rows


@app.route("/")
def index():
    return render_template("index.html", categories=lead_logic.ICP_CATEGORIES,
                            has_env_key=bool(os.environ.get("GOOGLE_MAPS_API_KEY")))


@app.route("/api/search", methods=["POST"])
def api_search():
    api_key = get_api_key()
    if not api_key:
        return jsonify({"error": "Kein API-Key gesetzt (GOOGLE_MAPS_API_KEY oder im Feld oben eintragen)."}), 400

    data = request.get_json(force=True)
    region_input = (data.get("region") or "").strip()
    category = (data.get("category") or "").strip()
    count = int(data.get("count") or 20)
    radius_km = min(float(data.get("radius_km") or 0), 50)  # Google erlaubt max. 50 km Umkreis

    if not region_input or not category:
        return jsonify({"error": "Region und Kategorie werden benoetigt."}), 400

    regions = [r.strip() for r in region_input.split(",") if r.strip()]

    total_found = 0
    new_place_ids = []
    errors = []
    for region in regions:
        try:
            location_bias = None
            if radius_km > 0:
                center = lead_logic.geocode_region(api_key, region)
                if center:
                    location_bias = {"center": center, "radius": radius_km * 1000}

            query = f"{category} in {region}"
            places = lead_logic.search_places(api_key, query, count, location_bias=location_bias)
            enriched = [lead_logic.enrich_place(api_key, p, region, category) for p in places]
            lead_logic.finalize_leads(enriched, known=db.get_all_leads(include_hidden=True))

            total_found += len(places)
            new_place_ids.extend(db.upsert_leads(enriched))
            db.remember_search(region, category, count, radius_km=radius_km)
        except RuntimeError as e:
            errors.append(f"{region}: {e}")

    if errors and not new_place_ids and total_found == 0:
        return jsonify({"error": "; ".join(errors)}), 502

    radius_label = f", Umkreis {radius_km:g} km" if radius_km > 0 else ""
    db.log_action("search", f"Suche '{category}' in {region_input}{radius_label}: {total_found} Treffer, "
                             f"{len(new_place_ids)} neu")

    return jsonify({
        "found": total_found,
        "new": len(new_place_ids),
        "new_place_ids": new_place_ids,
        "errors": errors,
    })


@app.route("/api/sync", methods=["POST"])
def api_sync():
    """Fuehrt alle bisher gemerkten Suchen (Region+Kategorie) erneut aus und
    fuegt nur wirklich neue Treffer hinzu - z.B. frisch eroeffnete Laeden,
    die beim letzten Lauf noch nicht in Google Maps gelistet waren."""
    api_key = get_api_key()
    if not api_key:
        return jsonify({"error": "Kein API-Key gesetzt."}), 400

    watched = db.get_watched_searches()
    if not watched:
        return jsonify({"error": "Noch keine gespeicherten Suchen - erst einmal 'Suchen' nutzen."}), 400

    new_place_ids = []
    errors = []
    for w in watched:
        try:
            location_bias = None
            radius_km = w.get("radius_km") or 0
            if radius_km > 0:
                center = lead_logic.geocode_region(api_key, w["region"])
                if center:
                    location_bias = {"center": center, "radius": radius_km * 1000}

            query = f"{w['category']} in {w['region']}"
            places = lead_logic.search_places(api_key, query, w["count"], location_bias=location_bias)
            enriched = [lead_logic.enrich_place(api_key, p, w["region"], w["category"]) for p in places]
            lead_logic.finalize_leads(enriched, known=db.get_all_leads(include_hidden=True))
            new_place_ids.extend(db.upsert_leads(enriched))
        except RuntimeError as e:
            errors.append(f"{w['category']} in {w['region']}: {e}")

    db.log_action("sync", f"Sync: {len(watched)} gespeicherte Suchen geprueft, {len(new_place_ids)} neu")

    return jsonify({
        "synced_searches": len(watched),
        "new": len(new_place_ids),
        "new_place_ids": new_place_ids,
        "errors": errors,
    })


@app.route("/api/leads")
def api_leads():
    hot_only = request.args.get("hot_only") == "1"
    region = request.args.get("region") or None
    category = request.args.get("category") or None
    tier = request.args.get("tier") or None
    status = request.args.get("status") or None
    opening_status = request.args.get("opening_status") or None
    return jsonify(annotate_chains(db.get_all_leads(hot_only=hot_only, region=region, category=category,
                                                     tier=tier, status=status, opening_status=opening_status,
                                                     include_hidden=True)))


@app.route("/api/leads/<place_id>", methods=["PATCH"])
def api_update_lead(place_id):
    data = request.get_json(force=True) or {}
    status = data.get("status")
    notes = data.get("notes")
    hidden = data.get("hidden")
    assigned_to = data.get("assigned_to")

    lead = db.get_lead(place_id)
    if not lead:
        return jsonify({"error": "Lead nicht gefunden."}), 404

    db.update_lead(place_id, status=status, notes=notes, hidden=hidden, assigned_to=assigned_to)

    if hidden is not None and bool(hidden) != bool(lead["hidden"]):
        payload = [{"place_id": place_id, "previous": {"hidden": lead["hidden"], "hidden_at": lead["hidden_at"]}}]
        desc = f"{lead['name']}: {'ausgeblendet' if hidden else 'eingeblendet'}"
        db.log_action("hide" if hidden else "unhide", desc, payload=payload, undoable=True)

    if status is not None and status != lead["status"]:
        payload = [{"place_id": place_id, "previous": {"status": lead["status"]}}]
        db.log_action("status_change", f"{lead['name']}: Status '{lead['status']}' -> '{status}'",
                       payload=payload, undoable=True)

    if assigned_to is not None and assigned_to != (lead.get("assigned_to") or ""):
        payload = [{"place_id": place_id, "previous": {"assigned_to": lead.get("assigned_to") or ""}}]
        desc = f"{lead['name']}: Zugewiesen an '{lead.get('assigned_to') or '–'}' -> '{assigned_to or '–'}'"
        db.log_action("assign", desc, payload=payload, undoable=True)

    return jsonify({"ok": True})


@app.route("/api/leads/bulk-assign", methods=["POST"])
def api_bulk_assign():
    data = request.get_json(force=True) or {}
    ids = data.get("ids") or []
    assigned_to = (data.get("assigned_to") or "").strip()
    if not ids:
        return jsonify({"error": "Keine Leads ausgewaehlt."}), 400
    previous = db.bulk_assign_leads(ids, assigned_to)
    log_id = None
    if previous:
        desc = f"{len(previous)} Leads zugewiesen an '{assigned_to or '–'}'"
        log_id = db.log_action("bulk_assign", desc, payload=previous, undoable=True)
    return jsonify({"changed": len(previous), "log_id": log_id})


@app.route("/api/leads/hide-before", methods=["POST"])
def api_hide_before():
    data = request.get_json(force=True) or {}
    cutoff_date = (data.get("date") or "").strip()
    if not cutoff_date:
        return jsonify({"error": "Datum wird benoetigt."}), 400
    previous = db.hide_leads_before(cutoff_date)
    log_id = None
    if previous:
        log_id = db.log_action("bulk_hide", f"{len(previous)} Leads bis {cutoff_date} ausgeblendet",
                                payload=previous, undoable=True)
    return jsonify({"hidden": len(previous), "log_id": log_id})


@app.route("/api/recheck", methods=["POST"])
def api_recheck():
    """Liest die Website aller Leads erneut (ohne Google-Aufrufe), ergaenzt erkannte Systeme in der Spalte
    'System', eine Kontakt-E-Mail und einen Inhaber-/Ansprechpartner-Namen (aus dem Impressum, falls noch
    keine/keiner vorhanden), bestimmt die Ketten neu und berechnet den Score neu. Bereits erkannte
    Systeme/E-Mails/Namen bleiben erhalten, Status/Notizen/Ausgeblendet bleiben unberuehrt. Undo-faehig."""
    all_leads = db.get_all_leads(include_hidden=True)
    with_site = [l for l in all_leads if l.get("website")]

    with ThreadPoolExecutor(max_workers=8) as pool:
        html_by_id = dict(pool.map(lambda l: (l["place_id"], lead_logic.fetch_website_html(l["website"])), with_site))

    # Impressum nur fuer Leads ohne bisherigen Namen abrufen (ein zweiter Netzwerk-Aufruf pro Lead)
    need_owner = [l for l in with_site if not (l.get("owner_name") or "") and html_by_id.get(l["place_id"])]
    impressum_urls = {l["place_id"]: lead_logic.find_impressum_url(l["website"], html_by_id[l["place_id"]])
                       for l in need_owner}
    with ThreadPoolExecutor(max_workers=8) as pool:
        impressum_html_by_id = dict(pool.map(
            lambda pid: (pid, lead_logic.fetch_website_html(impressum_urls[pid]) if impressum_urls[pid] else ""),
            impressum_urls))

    chain_counts = lead_logic.chain_sizes(all_leads)
    updates, previous = [], []
    for lead in all_leads:
        html = html_by_id.get(lead["place_id"], "")
        old_systems = lead.get("competitor_system") or ""
        systems = (lead_logic.merge_systems(old_systems, lead_logic.detect_competitor(lead["website"], html, []))
                   if html else old_systems)
        chain = int(chain_counts.get(lead["place_id"], 1) >= 2)
        old_email = lead.get("email") or ""
        email = old_email or (lead_logic.detect_email(lead["website"], html) if html else "")
        old_owner = lead.get("owner_name") or ""
        owner_name = old_owner or lead_logic.detect_owner_name(lead["name"], impressum_html_by_id.get(lead["place_id"], ""))
        if (systems == old_systems and chain == int(bool(lead.get("chain_flag")))
                and email == old_email and owner_name == old_owner):
            continue
        pain_points = [p for p in (lead.get("pain_points") or "").split(", ") if p]
        icp_score, icp_tier = lead_logic.compute_icp_score(
            category=lead["category_query"], rating_count=lead.get("rating_count") or 0, competitor=systems,
            chain_flag=bool(chain), pain_points=pain_points, opening_status=lead.get("opening_status") or "Etabliert")
        fields = {"competitor_system": systems, "chain_flag": chain, "icp_score": icp_score, "icp_tier": icp_tier,
                  "score": lead_logic.compute_score(systems, bool(lead.get("likely_new"))), "email": email,
                  "owner_name": owner_name}
        previous.append({"place_id": lead["place_id"], "previous": {k: lead.get(k) for k in fields}})
        updates.append((lead["place_id"], fields))

    db.set_lead_fields(updates)
    unreadable = sum(1 for l in with_site if not html_by_id.get(l["place_id"]))
    if updates:
        db.log_action("recheck", f"Erkennung neu geprueft: {len(updates)} von {len(all_leads)} Leads aktualisiert",
                       payload=previous, undoable=True)
    return jsonify({"checked": len(all_leads), "changed": len(updates), "unreadable": unreadable})


@app.route("/api/backfill-hours", methods=["POST"])
def api_backfill_hours():
    """Holt fuer bereits gespeicherte Leads ohne Oeffnungszeiten die aktuellen Oeffnungszeiten per Google
    Place Details nach (schmale Field Mask, kein Text-Search-Aufruf) - fuer Leads, die vor Einfuehrung der
    Oeffnungszeiten-Spalte gespeichert wurden. Braucht einen Google-API-Key. Undo-faehig."""
    api_key = get_api_key()
    if not api_key:
        return jsonify({"error": "Kein API-Key hinterlegt."}), 400

    all_leads = db.get_all_leads(include_hidden=True)
    need_hours = [l for l in all_leads if not (l.get("opening_hours") or "")]

    with ThreadPoolExecutor(max_workers=8) as pool:
        hours_by_id = dict(pool.map(
            lambda l: (l["place_id"], lead_logic.get_current_opening_hours(api_key, l["place_id"])), need_hours))

    updates, previous = [], []
    for lead in need_hours:
        formatted = lead_logic.format_weekly_hours(hours_by_id.get(lead["place_id"]))
        if not formatted:
            continue
        previous.append({"place_id": lead["place_id"], "previous": {"opening_hours": lead.get("opening_hours")}})
        updates.append((lead["place_id"], {"opening_hours": formatted}))

    db.set_lead_fields(updates)
    if updates:
        db.log_action("backfill_hours", f"Oeffnungszeiten nachgeladen: {len(updates)} von {len(need_hours)} Leads",
                       payload=previous, undoable=True)
    return jsonify({"checked": len(need_hours), "changed": len(updates)})


@app.route("/api/logs")
def api_logs():
    limit = int(request.args.get("limit", 50))
    return jsonify(db.get_logs(limit=limit))


@app.route("/api/logs/<int:log_id>/undo", methods=["POST"])
def api_undo_log(log_id):
    result = db.undo_log(log_id)
    if not result:
        return jsonify({"error": "Aktion kann nicht rueckgaengig gemacht werden (nicht gefunden, "
                                  "schon rueckgaengig gemacht, oder nicht rueckgaengig machbar)."}), 400
    db.log_action("undo", f"Rueckgaengig gemacht: {result['description']}",
                   payload=result["redo_payload"], undoable=bool(result["redo_payload"]))
    return jsonify({"ok": True, "count": result["count"]})


@app.route("/api/export", methods=["POST"])
def api_export():
    """Exportiert genau die uebergebenen Leads (Formularfelder: format = csv|xlsx|hubspot, ids = place_ids,
    kommagetrennt, in der Reihenfolge der Anzeige). Bereits ausgeblendete Leads werden ignoriert. Die
    exportierten Leads werden danach ausgeblendet und als undoable Log-Eintrag gespeichert."""
    fmt = request.form.get("format", "csv")
    ids = [i for i in (request.form.get("ids") or "").split(",") if i]
    not_hidden = {r["place_id"]: r for r in annotate_chains(db.get_all_leads())}
    rows = [not_hidden[i] for i in ids if i in not_hidden]
    if not rows:
        return jsonify({"error": "Keine exportierbaren Leads uebergeben."}), 400

    previous = db.hide_leads([r["place_id"] for r in rows])
    if previous:
        db.log_action("export", f"{len(previous)} Leads als {fmt.upper()} exportiert und ausgeblendet",
                       payload=previous, undoable=True)

    if fmt == "xlsx":
        data = exports.rows_to_xlsx_bytes(rows)
        return send_file(io.BytesIO(data), as_attachment=True,
                          download_name=exports.timestamped("leads", "xlsx"),
                          mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    if fmt == "hubspot":
        data = exports.rows_to_hubspot_csv_bytes(rows)
        return send_file(io.BytesIO(data), as_attachment=True,
                          download_name=exports.timestamped("leads_hubspot", "csv"), mimetype="text/csv")

    data = exports.rows_to_csv_bytes(rows)
    return send_file(io.BytesIO(data), as_attachment=True,
                      download_name=exports.timestamped("leads", "csv"), mimetype="text/csv")


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5050, debug=False)
