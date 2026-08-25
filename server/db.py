import sqlite3
import json
import os
import threading
from typing import Any, Dict, List, Optional

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data")
DB_PATH = os.path.join(DATA_DIR, "mediqueue.db")

_local = threading.local()


def get_db_connection() -> sqlite3.Connection:
    if not hasattr(_local, "conn") or _local.conn is None or getattr(_local, "db_path", None) != DB_PATH:
        if hasattr(_local, "conn") and _local.conn is not None:
            try:
                _local.conn.close()
            except Exception:
                pass
        os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
        conn = sqlite3.connect(DB_PATH, timeout=10.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA foreign_keys=ON;")
        _local.conn = conn
        _local.db_path = DB_PATH
    return _local.conn


def init_db() -> None:
    conn = get_db_connection()
    with conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                username TEXT PRIMARY KEY,
                password_hash TEXT NOT NULL,
                insurance TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS doctors (
                name TEXT PRIMARY KEY,
                specialization TEXT NOT NULL,
                accepted_insurance TEXT NOT NULL,
                udp_port INTEGER NOT NULL,
                slots TEXT NOT NULL
            );
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS bookings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                doctor TEXT NOT NULL,
                slot TEXT NOT NULL,
                patient TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(doctor, slot)
            );
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS audit_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                trace_id TEXT,
                user TEXT,
                action TEXT NOT NULL,
                details TEXT
            );
        """)

    _seed_from_json(conn)


def _seed_from_json(conn: sqlite3.Connection) -> None:
    # Seed Users
    users_path = os.path.join(DATA_DIR, "users.json")
    if os.path.exists(users_path):
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM users")
        if cur.fetchone()[0] == 0:
            try:
                with open(users_path, "r", encoding="utf-8") as f:
                    users_data = json.load(f)
                    for username, uinfo in users_data.items():
                        pwd_hash = uinfo.get("password", "")
                        insurance_json = json.dumps(uinfo.get("insurance", []))
                        cur.execute(
                            "INSERT OR IGNORE INTO users (username, password_hash, insurance) VALUES (?, ?, ?)",
                            (username, pwd_hash, insurance_json)
                        )
            except Exception as e:
                print(f"Error seeding users from JSON: {e}")

    # Seed Doctors
    doctors_path = os.path.join(DATA_DIR, "doctors.json")
    if os.path.exists(doctors_path):
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM doctors")
        if cur.fetchone()[0] == 0:
            try:
                with open(doctors_path, "r", encoding="utf-8") as f:
                    doctors_data = json.load(f)
                    for doc_name, dinfo in doctors_data.items():
                        spec = dinfo.get("specialization", "General")
                        accepted = json.dumps(dinfo.get("accepted_insurance", []))
                        udp_port = dinfo.get("udp_port", 5000)
                        slots = json.dumps(dinfo.get("slots", []))
                        cur.execute(
                            "INSERT OR IGNORE INTO doctors (name, specialization, accepted_insurance, udp_port, slots) VALUES (?, ?, ?, ?, ?)",
                            (doc_name, spec, accepted, udp_port, slots)
                        )
            except Exception as e:
                print(f"Error seeding doctors from JSON: {e}")

    # Seed Bookings
    bookings_path = os.path.join(DATA_DIR, "bookings.json")
    if os.path.exists(bookings_path):
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM bookings")
        if cur.fetchone()[0] == 0:
            try:
                with open(bookings_path, "r", encoding="utf-8") as f:
                    content = f.read().strip()
                    if content:
                        bookings_data = json.loads(content)
                        for doc_name, slots in bookings_data.items():
                            if isinstance(slots, dict):
                                for slot, binfo in slots.items():
                                    patient = binfo.get("patient") if isinstance(binfo, dict) else binfo
                                    if patient:
                                        cur.execute(
                                            "INSERT OR IGNORE INTO bookings (doctor, slot, patient) VALUES (?, ?, ?)",
                                            (doc_name, slot, patient)
                                        )
            except Exception as e:
                print(f"Error seeding bookings from JSON: {e}")

    conn.commit()


def add_audit_log(action: str, user: Optional[str] = None, trace_id: Optional[str] = None, details: Optional[str] = None) -> None:
    conn = get_db_connection()
    with conn:
        conn.execute(
            "INSERT INTO audit_logs (action, user, trace_id, details) VALUES (?, ?, ?, ?)",
            (action, user, trace_id, details)
        )


def get_audit_logs(limit: int = 50) -> List[Dict[str, Any]]:
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT id, timestamp, trace_id, user, action, details FROM audit_logs ORDER BY id DESC LIMIT ?", (limit,))
    rows = cur.fetchall()
    return [dict(r) for r in rows]
