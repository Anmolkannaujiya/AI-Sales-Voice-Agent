import sqlite3
from datetime import datetime
from typing import Dict, List, Optional, Any

DB_FILE = "sales_agent.db"

EMPTY = "Not provided"

def get_connection():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            role      TEXT NOT NULL,
            content   TEXT NOT NULL,
            sentiment TEXT DEFAULT 'neutral',
            timestamp TEXT NOT NULL
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS leads (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            name       TEXT DEFAULT 'Not provided',
            company    TEXT DEFAULT 'Not provided',
            role       TEXT DEFAULT 'Not provided',
            email      TEXT DEFAULT 'Not provided',
            need       TEXT DEFAULT 'Not provided',
            budget     TEXT DEFAULT 'Not provided',
            timeline   TEXT DEFAULT 'Not provided',
            sentiment  TEXT DEFAULT 'neutral',
            status     TEXT DEFAULT 'In Progress',
            summary    TEXT DEFAULT '',
            transcript TEXT DEFAULT '',
            updated_at TEXT NOT NULL
        )
    """)

    # Migrate existing leads table: add columns that may be absent in older DBs
    existing_cols = {row[1] for row in cursor.execute("PRAGMA table_info(leads)")}
    for col, default in [
        ("role", "Not provided"),
        ("timeline", "Not provided"),
        ("sentiment", "neutral"),
        ("transcript", ""),
    ]:
        if col not in existing_cols:
            cursor.execute(f"ALTER TABLE leads ADD COLUMN {col} TEXT DEFAULT '{default}'")

    # Migrate messages: add sentiment column if absent
    existing_msg_cols = {row[1] for row in cursor.execute("PRAGMA table_info(messages)")}
    if "sentiment" not in existing_msg_cols:
        cursor.execute("ALTER TABLE messages ADD COLUMN sentiment TEXT DEFAULT 'neutral'")

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS appointments (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            lead_name  TEXT NOT NULL,
            lead_email TEXT DEFAULT 'Not provided',
            slot       TEXT NOT NULL,
            notes      TEXT DEFAULT '',
            created_at TEXT NOT NULL
        )
    """)

    existing_apt_cols = {row[1] for row in cursor.execute("PRAGMA table_info(appointments)")}
    if "lead_email" not in existing_apt_cols:
        cursor.execute("ALTER TABLE appointments ADD COLUMN lead_email TEXT DEFAULT 'Not provided'")

    conn.commit()
    conn.close()

# ── helpers ───────────────────────────────────────────────────────────────────

def _pick(new_val, old_val):
    """Return new_val if it is a real value, else keep old_val."""
    if new_val and str(new_val).strip().lower() not in (EMPTY.lower(), "", "none", "null"):
        return str(new_val).strip()
    return old_val

# ── messages ──────────────────────────────────────────────────────────────────

def save_message(role: str, content: str, sentiment: str = "neutral"):
    conn = get_connection()
    conn.execute(
        "INSERT INTO messages (role, content, sentiment, timestamp) VALUES (?, ?, ?, ?)",
        (role, content, sentiment, datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    )
    conn.commit()
    conn.close()

def get_messages() -> List[Dict[str, Any]]:
    conn = get_connection()
    rows = conn.execute(
        "SELECT id, role, content, sentiment, timestamp FROM messages ORDER BY id ASC"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]

# ── leads ─────────────────────────────────────────────────────────────────────

def get_latest_lead() -> Optional[Dict[str, Any]]:
    conn = get_connection()
    row = conn.execute("SELECT * FROM leads ORDER BY id DESC LIMIT 1").fetchone()
    conn.close()
    return dict(row) if row else None

def format_transcript() -> str:
    """Return a plain-text transcript of all messages stored in SQLite."""
    msgs = get_messages()
    lines = []
    for m in msgs:
        speaker = "Prospect" if m["role"] == "user" else "Agent"
        lines.append(f"[{m['timestamp']}] {speaker}: {m['content']}")
    return "\n".join(lines)

def upsert_lead(data: Dict[str, Any]) -> Dict[str, Any]:
    conn = get_connection()
    cursor = conn.cursor()
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    latest = get_latest_lead()
    transcript_text = format_transcript()

    fields = ["name", "company", "role", "email", "need", "budget", "timeline", "sentiment", "status", "summary"]

    if latest:
        lead_id = latest["id"]
        vals = {f: _pick(data.get(f, ""), latest.get(f, EMPTY)) for f in fields}
        cursor.execute("""
            UPDATE leads
            SET name=?, company=?, role=?, email=?, need=?, budget=?, timeline=?,
                sentiment=?, status=?, summary=?, transcript=?, updated_at=?
            WHERE id=?
        """, (
            vals["name"], vals["company"], vals["role"], vals["email"],
            vals["need"], vals["budget"], vals["timeline"],
            vals["sentiment"], vals["status"], vals["summary"], transcript_text, now_str, lead_id
        ))
    else:
        vals = {f: data.get(f, EMPTY) or EMPTY for f in fields}
        if not data.get("sentiment"):
            vals["sentiment"] = "neutral"
        cursor.execute("""
            INSERT INTO leads (name, company, role, email, need, budget, timeline, sentiment, status, summary, transcript, updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            vals["name"], vals["company"], vals["role"], vals["email"],
            vals["need"], vals["budget"], vals["timeline"],
            vals["sentiment"], vals["status"], vals["summary"], transcript_text, now_str
        ))

    conn.commit()
    conn.close()
    return get_latest_lead() or {}

# ── appointments ──────────────────────────────────────────────────────────────

def book_appointment(lead_name: str, slot: str, notes: str = "", lead_email: str = "Not provided") -> Dict[str, Any]:
    conn = get_connection()
    cursor = conn.cursor()
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    clean_name = lead_name if lead_name and lead_name != EMPTY else "Guest Lead"
    clean_email = lead_email if lead_email else EMPTY
    cursor.execute(
        "INSERT INTO appointments (lead_name, lead_email, slot, notes, created_at) VALUES (?, ?, ?, ?, ?)",
        (clean_name, clean_email, slot, notes, now_str)
    )
    apt_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return {
        "id": apt_id,
        "lead_name": clean_name,
        "lead_email": clean_email,
        "slot": slot,
        "notes": notes,
        "created_at": now_str
    }

def get_appointments() -> List[Dict[str, Any]]:
    conn = get_connection()
    rows = conn.execute("SELECT * FROM appointments ORDER BY id DESC").fetchall()
    conn.close()
    return [dict(r) for r in rows]

# ── reset ─────────────────────────────────────────────────────────────────────

def reset_database():
    conn = get_connection()
    conn.execute("DELETE FROM messages")
    conn.execute("DELETE FROM leads")
    conn.execute("DELETE FROM appointments")
    conn.commit()
    conn.close()
