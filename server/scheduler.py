import json
import threading
from typing import Any, Dict, List, Optional
from db import get_db_connection, init_db, add_audit_log
from cache import CacheManager

cache = CacheManager()


class Scheduler:

    def __init__(self):
        init_db()
        self.lock = threading.Lock()

    def get_all_bookings(self) -> Dict[str, Dict[str, str]]:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT doctor, slot, patient FROM bookings")
        rows = cur.fetchall()

        result: Dict[str, Dict[str, str]] = {}
        for r in rows:
            doc = r["doctor"]
            slot = r["slot"]
            patient = r["patient"]
            if doc not in result:
                result[doc] = {}
            result[doc][slot] = patient
        return result

    def remove_booking(self, doctor: str, slot: str) -> bool:
        conn = get_db_connection()
        with conn:
            cur = conn.cursor()
            cur.execute("DELETE FROM bookings WHERE doctor = ? AND slot = ?", (doctor, slot))
            if cur.rowcount > 0:
                add_audit_log(action="ADMIN_CANCEL_BOOKING", user="ADMIN", details=f"Doctor: {doctor}, Slot: {slot}")
                cache.invalidate_slots_cache()
                return True
        return False

    def get_slots(self, insurance: List[str], specialization: Optional[str] = None) -> Dict[str, Any]:
        cache_key = f"{','.join(sorted(insurance))}:{specialization or 'ALL'}"
        cached_result = cache.get_slots_cache(cache_key)
        if cached_result is not None:
            return cached_result

        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT name, specialization, accepted_insurance, udp_port, slots FROM doctors")
        doc_rows = cur.fetchall()

        cur.execute("SELECT doctor, slot FROM bookings")
        booked_rows = cur.fetchall()
        booked_map: Dict[str, set] = {}
        for r in booked_rows:
            booked_map.setdefault(r["doctor"], set()).add(r["slot"])

        filtered: Dict[str, Any] = {}
        for d in doc_rows:
            doc_name = d["name"]
            spec = d["specialization"]
            try:
                acc_ins = json.loads(d["accepted_insurance"])
            except Exception:
                acc_ins = []
            try:
                all_slots = json.loads(d["slots"])
            except Exception:
                all_slots = []
            udp_port = d["udp_port"]

            if insurance and not any(i in acc_ins for i in insurance):
                continue
            if specialization and specialization.lower() not in spec.lower():
                continue

            doc_booked = booked_map.get(doc_name, set())
            available = [s for s in all_slots if s not in doc_booked]

            filtered[doc_name] = {
                "slots": available,
                "accepted_insurance": acc_ins,
                "specialization": spec,
                "udp_port": udp_port,
            }

        cache.set_slots_cache(cache_key, filtered, ttl=60)
        return filtered

    def get_slots_by_insurance(self, insurance: List[str]) -> Dict[str, Any]:
        return self.get_slots(insurance)

    def book_slot(self, user: str, doctor: str, slot: str) -> Dict[str, Any]:
        conn = get_db_connection()
        with conn:
            cur = conn.cursor()
            cur.execute("SELECT specialization, udp_port, slots FROM doctors WHERE name = ?", (doctor,))
            doc_row = cur.fetchone()
            if not doc_row:
                return {"status": "UNAVAILABLE", "reason": "Doctor not found"}

            try:
                valid_slots = json.loads(doc_row["slots"])
            except Exception:
                valid_slots = []

            if slot not in valid_slots:
                return {"status": "UNAVAILABLE", "reason": "Slot does not exist"}

            cur.execute("SELECT id FROM bookings WHERE doctor = ? AND slot = ?", (doctor, slot))
            if cur.fetchone():
                return {"status": "UNAVAILABLE", "reason": "Slot already booked"}

            try:
                cur.execute(
                    "INSERT INTO bookings (doctor, slot, patient) VALUES (?, ?, ?)",
                    (doctor, slot, user)
                )
                add_audit_log(action="BOOK_APPOINTMENT", user=user, details=f"Doctor: {doctor}, Slot: {slot}")
                cache.invalidate_slots_cache()
                return {
                    "status": "BOOKED",
                    "doctor": doctor,
                    "slot": slot,
                    "udp_port": doc_row["udp_port"],
                    "specialization": doc_row["specialization"],
                }
            except Exception as e:
                return {"status": "UNAVAILABLE", "reason": f"Database error: {str(e)}"}

    def get_bookings_for_patient(self, user: str) -> List[Dict[str, Any]]:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            SELECT b.doctor, b.slot, b.patient, d.specialization
            FROM bookings b
            LEFT JOIN doctors d ON b.doctor = d.name
            WHERE b.patient = ?
        """, (user,))
        rows = cur.fetchall()

        results = []
        for r in rows:
            results.append({
                "doctor": r["doctor"],
                "specialization": r["specialization"] or "General",
                "slot": r["slot"],
                "patient": r["patient"],
            })
        results.sort(key=lambda x: (x["doctor"].lower(), x["slot"].lower()))
        return results

    def remove_booking_for_patient(self, user: str, doctor: str, slot: str) -> Dict[str, Any]:
        conn = get_db_connection()
        with conn:
            cur = conn.cursor()
            cur.execute("SELECT patient FROM bookings WHERE doctor = ? AND slot = ?", (doctor, slot))
            row = cur.fetchone()
            if not row:
                return {"status": "FAIL", "reason": "Booking not found"}
            if row["patient"] != user:
                return {"status": "FAIL", "reason": "You can only cancel your own appointments"}

            cur.execute("DELETE FROM bookings WHERE doctor = ? AND slot = ?", (doctor, slot))
            add_audit_log(action="CANCEL_APPOINTMENT", user=user, details=f"Doctor: {doctor}, Slot: {slot}")
            cache.invalidate_slots_cache()
            return {"status": "OK"}

    def get_all_doctors(self) -> Dict[str, Any]:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT name, specialization, accepted_insurance, udp_port, slots FROM doctors")
        rows = cur.fetchall()

        result = {}
        for r in rows:
            try:
                acc = json.loads(r["accepted_insurance"])
            except Exception:
                acc = []
            try:
                slots = json.loads(r["slots"])
            except Exception:
                slots = []
            result[r["name"]] = {
                "specialization": r["specialization"],
                "accepted_insurance": acc,
                "udp_port": r["udp_port"],
                "slots": slots,
            }
        return result

    def get_specializations(self) -> List[str]:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT DISTINCT specialization FROM doctors")
        rows = cur.fetchall()
        specs = {r["specialization"] for r in rows if r["specialization"]}
        return sorted(list(specs))

    def register_doctor(self, doctor: str, specialization: str, accepted_insurance: List[str], udp_port: int, slots: Optional[List[str]] = None) -> Dict[str, Any]:
        if not slots:
            slots = ["9AM", "11AM", "2PM", "4PM"]

        conn = get_db_connection()
        with conn:
            cur = conn.cursor()
            cur.execute("""
                INSERT OR REPLACE INTO doctors (name, specialization, accepted_insurance, udp_port, slots)
                VALUES (?, ?, ?, ?, ?)
            """, (doctor, specialization, json.dumps(accepted_insurance), udp_port, json.dumps(slots)))
            add_audit_log(action="REGISTER_DOCTOR", user=doctor, details=f"Spec: {specialization}, Port: {udp_port}")
            cache.invalidate_slots_cache()

        return {"status": "OK", "doctor": doctor, "udp_port": udp_port}
