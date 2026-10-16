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
                slots TEXT NOT NULL,
                password_hash TEXT DEFAULT ''
            );
        """)
        try:
            conn.execute("ALTER TABLE doctors ADD COLUMN password_hash TEXT DEFAULT '';")
        except Exception:
            pass
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
        try:
            conn.execute("ALTER TABLE bookings ADD COLUMN appointment_date TEXT DEFAULT CURRENT_DATE;")
        except Exception:
            pass
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
        conn.execute("""
            CREATE TABLE IF NOT EXISTS prescriptions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                doctor TEXT NOT NULL,
                patient TEXT NOT NULL,
                diagnosis TEXT NOT NULL,
                medications TEXT NOT NULL,
                instructions TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS patient_profiles (
                username TEXT PRIMARY KEY,
                dob TEXT,
                blood_group TEXT,
                allergies TEXT,
                chronic_conditions TEXT,
                emergency_contact TEXT,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(username) REFERENCES users(username)
            );
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS doctor_reviews (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                doctor TEXT NOT NULL,
                patient TEXT NOT NULL,
                rating INTEGER NOT NULL CHECK(rating BETWEEN 1 AND 5),
                review TEXT,
                session_id TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
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


def get_audit_logs(limit: int = 50, user: Optional[str] = None, action: Optional[str] = None, keyword: Optional[str] = None) -> List[Dict[str, Any]]:
    conn = get_db_connection()
    cur = conn.cursor()
    query = "SELECT id, timestamp, trace_id, user, action, details FROM audit_logs WHERE 1=1"
    params: List[Any] = []
    if user:
        query += " AND user LIKE ?"
        params.append(f"%{user}%")
    if action:
        query += " AND action LIKE ?"
        params.append(f"%{action}%")
    if keyword:
        query += " AND (details LIKE ? OR action LIKE ? OR trace_id LIKE ?)"
        params.extend([f"%{keyword}%", f"%{keyword}%", f"%{keyword}%"])
    query += " ORDER BY id DESC LIMIT ?"
    params.append(limit)
    cur.execute(query, tuple(params))
    rows = cur.fetchall()
    return [dict(r) for r in rows]


def export_audit_logs_to_csv(filepath: Optional[str] = None, user: Optional[str] = None, action: Optional[str] = None, keyword: Optional[str] = None, limit: int = 1000) -> str:
    import csv
    logs = get_audit_logs(limit=limit, user=user, action=action, keyword=keyword)
    if not filepath:
        export_dir = os.path.join(DATA_DIR, "exports")
        os.makedirs(export_dir, exist_ok=True)
        filepath = os.path.join(export_dir, "audit_logs.csv")
    else:
        os.makedirs(os.path.dirname(os.path.abspath(filepath)), exist_ok=True)
    with open(filepath, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["id", "timestamp", "trace_id", "user", "action", "details"])
        for log in logs:
            writer.writerow([
                log.get("id"),
                log.get("timestamp"),
                log.get("trace_id", ""),
                log.get("user", ""),
                log.get("action", ""),
                log.get("details", "")
            ])
    return os.path.abspath(filepath)



def save_prescription(session_id: str, doctor: str, patient: str, diagnosis: str, medications: List[Dict[str, Any]], instructions: str = "") -> int:
    conn = get_db_connection()
    with conn:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO prescriptions (session_id, doctor, patient, diagnosis, medications, instructions) VALUES (?, ?, ?, ?, ?, ?)",
            (session_id, doctor, patient, diagnosis, json.dumps(medications), instructions)
        )
        return cur.lastrowid


def get_prescriptions_for_patient(patient: str) -> List[Dict[str, Any]]:
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT id, session_id, doctor, patient, diagnosis, medications, instructions, created_at FROM prescriptions WHERE patient = ? ORDER BY id DESC",
        (patient,)
    )
    rows = cur.fetchall()
    result = []
    for r in rows:
        item = dict(r)
        try:
            item["medications"] = json.loads(item["medications"])
        except Exception:
            item["medications"] = []
        result.append(item)
    return result


def get_prescription_by_session(session_id: str) -> Optional[Dict[str, Any]]:
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT id, session_id, doctor, patient, diagnosis, medications, instructions, created_at FROM prescriptions WHERE session_id = ?",
        (session_id,)
    )
    row = cur.fetchone()
    if row:
        item = dict(row)
        try:
            item["medications"] = json.loads(item["medications"])
        except Exception:
            item["medications"] = []
        return item
    return None


def save_patient_profile(username: str, dob: str = "", blood_group: str = "", allergies: List[str] | None = None, chronic_conditions: List[str] | None = None, emergency_contact: str = "") -> None:
    conn = get_db_connection()
    with conn:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO patient_profiles (username, dob, blood_group, allergies, chronic_conditions, emergency_contact, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(username) DO UPDATE SET
                dob = excluded.dob,
                blood_group = excluded.blood_group,
                allergies = excluded.allergies,
                chronic_conditions = excluded.chronic_conditions,
                emergency_contact = excluded.emergency_contact,
                updated_at = CURRENT_TIMESTAMP
        """, (
            username,
            dob,
            blood_group,
            json.dumps(allergies or []),
            json.dumps(chronic_conditions or []),
            emergency_contact
        ))


def get_patient_profile(username: str) -> Optional[Dict[str, Any]]:
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT username, dob, blood_group, allergies, chronic_conditions, emergency_contact, updated_at FROM patient_profiles WHERE username = ?",
        (username,)
    )
    row = cur.fetchone()
    if row:
        item = dict(row)
        try:
            item["allergies"] = json.loads(item["allergies"])
        except Exception:
            item["allergies"] = []
        try:
            item["chronic_conditions"] = json.loads(item["chronic_conditions"])
        except Exception:
            item["chronic_conditions"] = []
        return item
    return None


def save_doctor_review(doctor: str, patient: str, rating: int, review: str = "", session_id: str = "") -> int:
    conn = get_db_connection()
    with conn:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO doctor_reviews (doctor, patient, rating, review, session_id) VALUES (?, ?, ?, ?, ?)",
            (doctor, patient, max(1, min(5, int(rating))), review, session_id)
        )
        return cur.lastrowid


def get_doctor_rating_stats(doctor: str) -> Dict[str, Any]:
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT COUNT(*) as count, AVG(rating) as avg_rating FROM doctor_reviews WHERE doctor = ?",
        (doctor,)
    )
    row = cur.fetchone()
    count = row["count"] if row else 0
    avg_rating = round(row["avg_rating"], 1) if (row and row["avg_rating"]) else 5.0
    return {
        "doctor": doctor,
        "total_reviews": count,
        "average_rating": avg_rating,
    }


def get_all_doctor_ratings() -> Dict[str, Dict[str, Any]]:
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT doctor, COUNT(*) as count, AVG(rating) as avg_rating FROM doctor_reviews GROUP BY doctor"
    )
    res = {}
    for row in cur.fetchall():
        res[row["doctor"]] = {
            "total_reviews": row["count"],
            "average_rating": round(row["avg_rating"], 1) if row["avg_rating"] else 5.0,
        }
    return res


def get_doctor_reviews_list(doctor: str, limit: int = 10) -> List[Dict[str, Any]]:
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT id, doctor, patient, rating, review, created_at FROM doctor_reviews WHERE doctor = ? ORDER BY id DESC LIMIT ?",
        (doctor, limit)
    )
    return [dict(r) for r in cur.fetchall()]


def get_upcoming_bookings(days_ahead: int = 2) -> List[Dict[str, Any]]:
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT id, doctor, slot, patient, COALESCE(appointment_date, date('now')) as appointment_date
        FROM bookings
        WHERE appointment_date >= date('now') AND appointment_date <= date('now', '+' || ? || ' days')
        ORDER BY appointment_date ASC, slot ASC
    """, (days_ahead,))
    return [dict(r) for r in cur.fetchall()]
