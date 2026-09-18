#!/usr/bin/env python3
"""
Shore Lead Finder - lokale Web-App mit persistenter Datenbank.

Start:
    export GOOGLE_MAPS_API_KEY="dein-key"
    python3 app.py
    -> oeffnet auf http://127.0.0.1:5050

Siehe SETUP.md fuer die einmalige Google-API-Key-Einrichtung.
"""

import os

from flask import Flask, jsonify, render_template, request, send_file
import io

import db
import exports
import lead_logic

app = Flask(__name__)
db.init_db()


def get_api_key():
    return request.headers.get("X-Api-Key") or os.environ.get("GOOGLE_MAPS_API_KEY")


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
            lead_logic.finalize_leads(enriched)

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
            lead_logic.finalize_leads(enriched)
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
    return jsonify(db.get_all_leads(hot_only=hot_only, region=region, category=category,
                                     tier=tier, status=status, opening_status=opening_status,
                                     include_hidden=True))


@app.route("/api/leads/<place_id>", methods=["PATCH"])
def api_update_lead(place_id):
    data = request.get_json(force=True) or {}
    status = data.get("status")
    notes = data.get("notes")
    hidden = data.get("hidden")

    lead = db.get_lead(place_id)
    if not lead:
        return jsonify({"error": "Lead nicht gefunden."}), 404

    db.update_lead(place_id, status=status, notes=notes, hidden=hidden)

    if hidden is not None and bool(hidden) != bool(lead["hidden"]):
        payload = [{"place_id": place_id, "previous": {"hidden": lead["hidden"], "hidden_at": lead["hidden_at"]}}]
        desc = f"{lead['name']}: {'ausgeblendet' if hidden else 'eingeblendet'}"
        db.log_action("hide" if hidden else "unhide", desc, payload=payload, undoable=True)

    if status is not None and status != lead["status"]:
        payload = [{"place_id": place_id, "previous": {"status": lead["status"]}}]
        db.log_action("status_change", f"{lead['name']}: Status '{lead['status']}' -> '{status}'",
                       payload=payload, undoable=True)

    return jsonify({"ok": True})


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


@app.route("/api/export")
def api_export():
    fmt = request.args.get("format", "csv")
    hot_only = request.args.get("hot_only") == "1"
    rows = db.get_all_leads(hot_only=hot_only)

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
