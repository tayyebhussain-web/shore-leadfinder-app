"""
SQLite-Persistenz. Eine leads.db liegt im selben Ordner und waechst mit jedem
Search/Sync-Lauf. Nichts wird ueberschrieben - Sync fuegt nur neue Leads hinzu.
"""

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

DB_PATH = Path(__file__).parent / "leads.db"
CET = ZoneInfo("Europe/Berlin")


def _now_cet() -> str:
    return datetime.now(CET).strftime("%Y-%m-%d %H:%M:%S")


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_conn()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS leads (
            place_id TEXT PRIMARY KEY,
            name TEXT,
            address TEXT,
            phone TEXT,
            website TEXT,
            rating REAL,
            rating_count INTEGER,
            business_status TEXT,
            open_now INTEGER,
            category_query TEXT,
            region_query TEXT,
            likely_new INTEGER,
            opening_status TEXT,
            opening_date TEXT,
            competitor_system TEXT,
            pain_points TEXT,
            score TEXT,
            chain_flag INTEGER,
            first_seen TEXT,
            icp_score INTEGER,
            icp_tier TEXT,
            status TEXT DEFAULT 'Neu',
            notes TEXT DEFAULT '',
            hidden INTEGER DEFAULT 0,
            hidden_at TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS watched_searches (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            region TEXT,
            category TEXT,
            count INTEGER,
            radius_km REAL DEFAULT 0,
            created_at TEXT,
            UNIQUE(region, category)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS action_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            action_type TEXT,
            description TEXT,
            payload TEXT,
            undoable INTEGER DEFAULT 0,
            undone INTEGER DEFAULT 0,
            created_at TEXT
        )
    """)
    conn.commit()
    _migrate_add_columns(conn)
    conn.close()


def _migrate_add_columns(conn):
    """Fuer bestehende leads.db aus einer frueheren Version: fehlende Spalten nachruesten."""
    existing = {row["name"] for row in conn.execute("PRAGMA table_info(leads)").fetchall()}
    additions = {
        "icp_score": "INTEGER",
        "icp_tier": "TEXT",
        "status": "TEXT DEFAULT 'Neu'",
        "notes": "TEXT DEFAULT ''",
        "opening_status": "TEXT",
        "opening_date": "TEXT",
        "hidden": "INTEGER DEFAULT 0",
        "hidden_at": "TEXT",
    }
    for col, coltype in additions.items():
        if col not in existing:
            conn.execute(f"ALTER TABLE leads ADD COLUMN {col} {coltype}")

    ws_existing = {row["name"] for row in conn.execute("PRAGMA table_info(watched_searches)").fetchall()}
    if "radius_km" not in ws_existing:
        conn.execute("ALTER TABLE watched_searches ADD COLUMN radius_km REAL DEFAULT 0")
    conn.commit()


def upsert_leads(leads: list) -> list:
    """Fuegt nur wirklich neue Leads ein (place_id noch nicht in DB). Gibt die place_ids der neu
    eingefuegten Leads zurueck (leer, wenn alle schon bekannt waren)."""
    if not leads:
        return []
    conn = get_conn()
    cur = conn.cursor()
    new_place_ids = []
    for lead in leads:
        cur.execute("SELECT 1 FROM leads WHERE place_id = ?", (lead["place_id"],))
        if cur.fetchone():
            continue
        cur.execute("""
            INSERT INTO leads (place_id, name, address, phone, website, rating, rating_count,
                business_status, open_now, category_query, region_query, likely_new,
                opening_status, opening_date, competitor_system, pain_points, score, chain_flag, first_seen,
                icp_score, icp_tier, status, notes)
            VALUES (:place_id, :name, :address, :phone, :website, :rating, :rating_count,
                :business_status, :open_now, :category_query, :region_query, :likely_new,
                :opening_status, :opening_date, :competitor_system, :pain_points, :score, :chain_flag, :first_seen,
                :icp_score, :icp_tier, :status, :notes)
        """, {**lead, "open_now": int(bool(lead.get("open_now"))), "likely_new": int(bool(lead.get("likely_new"))),
              "chain_flag": int(bool(lead.get("chain_flag"))), "icp_score": lead.get("icp_score", 0),
              "icp_tier": lead.get("icp_tier", ""), "status": lead.get("status", "Neu"),
              "notes": lead.get("notes", ""), "opening_status": lead.get("opening_status", "Etabliert"),
              "opening_date": lead.get("opening_date", "")})
        new_place_ids.append(lead["place_id"])
    conn.commit()
    conn.close()
    return new_place_ids


def remember_search(region: str, category: str, count: int, radius_km: float = 0):
    conn = get_conn()
    conn.execute("""
        INSERT INTO watched_searches (region, category, count, radius_km, created_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(region, category) DO UPDATE SET count = excluded.count, radius_km = excluded.radius_km
    """, (region, category, count, radius_km, _now_cet()))
    conn.commit()
    conn.close()


def get_watched_searches() -> list:
    conn = get_conn()
    rows = conn.execute("SELECT region, category, count, radius_km FROM watched_searches").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_all_leads(hot_only: bool = False, region: str = None, category: str = None,
                   tier: str = None, status: str = None, opening_status: str = None,
                   include_hidden: bool = False) -> list:
    conn = get_conn()
    query = "SELECT * FROM leads WHERE 1=1"
    params = []
    if not include_hidden:
        query += " AND (hidden IS NULL OR hidden = 0)"
    if hot_only:
        query += " AND score = 'Heiss'"
    if region:
        query += " AND region_query = ?"
        params.append(region)
    if category:
        query += " AND category_query = ?"
        params.append(category)
    if tier:
        query += " AND icp_tier = ?"
        params.append(tier)
    if status:
        query += " AND status = ?"
        params.append(status)
    if opening_status:
        query += " AND opening_status = ?"
        params.append(opening_status)
    query += " ORDER BY icp_score DESC, rating_count DESC"
    rows = conn.execute(query, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_lead(place_id: str) -> dict:
    conn = get_conn()
    row = conn.execute("SELECT * FROM leads WHERE place_id = ?", (place_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def update_lead(place_id: str, status: str = None, notes: str = None, hidden: bool = None) -> bool:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM leads WHERE place_id = ?", (place_id,))
    if not cur.fetchone():
        conn.close()
        return False
    if status is not None:
        cur.execute("UPDATE leads SET status = ? WHERE place_id = ?", (status, place_id))
    if notes is not None:
        cur.execute("UPDATE leads SET notes = ? WHERE place_id = ?", (notes, place_id))
    if hidden is not None:
        if hidden:
            cur.execute("UPDATE leads SET hidden = 1, hidden_at = ? WHERE place_id = ?", (_now_cet(), place_id))
        else:
            cur.execute("UPDATE leads SET hidden = 0, hidden_at = NULL WHERE place_id = ?", (place_id,))
    conn.commit()
    conn.close()
    return True


def hide_leads(place_ids: list) -> list:
    """Setzt hidden=1 fuer die gegebenen place_ids (sofern noch nicht ausgeblendet). Gibt fuer jeden
    tatsaechlich geaenderten Lead den vorherigen Zustand zurueck (fuer Undo-Log)."""
    if not place_ids:
        return []
    conn = get_conn()
    placeholders = ",".join("?" * len(place_ids))
    rows = conn.execute(f"""
        SELECT place_id, hidden, hidden_at FROM leads
        WHERE place_id IN ({placeholders}) AND (hidden IS NULL OR hidden = 0)
    """, place_ids).fetchall()
    previous = [{"place_id": r["place_id"], "previous": {"hidden": r["hidden"], "hidden_at": r["hidden_at"]}}
                for r in rows]
    if previous:
        now = _now_cet()
        conn.executemany("UPDATE leads SET hidden = 1, hidden_at = ? WHERE place_id = ?",
                          [(now, p["place_id"]) for p in previous])
    conn.commit()
    conn.close()
    return previous


def hide_leads_before(cutoff_date: str) -> list:
    """Markiert alle Leads mit first_seen <= cutoff_date als ausgeblendet (z.B. 'schon in HubSpot').
    cutoff_date im Format YYYY-MM-DD. Gibt die vorherigen Zustaende zurueck (fuer Undo-Log)."""
    conn = get_conn()
    rows = conn.execute("""
        SELECT place_id FROM leads WHERE date(first_seen) <= date(?) AND (hidden IS NULL OR hidden = 0)
    """, (cutoff_date,)).fetchall()
    conn.close()
    return hide_leads([r["place_id"] for r in rows])


def log_action(action_type: str, description: str, payload: list = None, undoable: bool = False) -> int:
    conn = get_conn()
    cur = conn.execute("""
        INSERT INTO action_log (action_type, description, payload, undoable, undone, created_at)
        VALUES (?, ?, ?, ?, 0, ?)
    """, (action_type, description, json.dumps(payload) if payload else None, int(undoable), _now_cet()))
    log_id = cur.lastrowid
    conn.commit()
    conn.close()
    return log_id


def get_logs(limit: int = 50) -> list:
    conn = get_conn()
    rows = conn.execute("SELECT * FROM action_log ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def undo_log(log_id: int) -> dict:
    """Macht die in payload gespeicherten Feldaenderungen rueckgaengig. Gibt None zurueck, wenn der
    Log-Eintrag nicht existiert, nicht rueckgaengig machbar ist oder schon rueckgaengig gemacht wurde.
    Gibt zusaetzlich ein 'redo_payload' zurueck: den Zustand unmittelbar VOR dem Rueckgaengig-Machen,
    damit dieser Undo-Schritt selbst wieder rueckgaengig gemacht werden kann (= Redo)."""
    conn = get_conn()
    row = conn.execute("SELECT * FROM action_log WHERE id = ?", (log_id,)).fetchone()
    if not row or not row["undoable"] or row["undone"]:
        conn.close()
        return None
    payload = json.loads(row["payload"] or "[]")
    redo_payload = []
    for item in payload:
        pid = item["place_id"]
        prev = item["previous"]
        fields = list(prev.keys())
        current = conn.execute(f"SELECT {', '.join(fields)} FROM leads WHERE place_id = ?", (pid,)).fetchone()
        if current is None:
            continue
        redo_payload.append({"place_id": pid, "previous": {f: current[f] for f in fields}})
        set_clause = ", ".join(f"{key} = ?" for key in fields)
        conn.execute(f"UPDATE leads SET {set_clause} WHERE place_id = ?", list(prev.values()) + [pid])
    conn.execute("UPDATE action_log SET undone = 1 WHERE id = ?", (log_id,))
    conn.commit()
    conn.close()
    return {"description": row["description"], "count": len(payload), "redo_payload": redo_payload}
