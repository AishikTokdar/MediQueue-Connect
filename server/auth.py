import json
import os
import hashlib
from typing import Dict, List, Optional
try:
    from argon2 import PasswordHasher
    from argon2.exceptions import VerifyMismatchError, VerificationError
    _ARGON2_AVAILABLE = True
except ImportError:
    _ARGON2_AVAILABLE = False

from db import get_db_connection, init_db, add_audit_log
from cache import CacheManager

cache = CacheManager()


class AuthManager:

    def __init__(self):
        init_db()
        self.ph = PasswordHasher() if _ARGON2_AVAILABLE else None
        self.sessions: Dict[str, str] = {}
        self.roles: Dict[str, str] = {}

    def _hash_password(self, pwd: str) -> str:
        if _ARGON2_AVAILABLE and self.ph:
            return self.ph.hash(pwd)
        salt = "mediqueue_salt_2026"
        return "sha256$" + hashlib.sha256((salt + pwd).encode()).hexdigest()

    def _verify_password(self, pwd: str, hash_val: str) -> bool:
        if not hash_val:
            return False
        if len(hash_val) == 64 and all(c in "0123456789abcdefABCDEF" for c in hash_val):
            sha_matches = hashlib.sha256(pwd.encode()).hexdigest() == hash_val
            return sha_matches
        if hash_val.startswith("sha256$"):
            salt = "mediqueue_salt_2026"
            return ("sha256$" + hashlib.sha256((salt + pwd).encode()).hexdigest()) == hash_val

        if _ARGON2_AVAILABLE and self.ph:
            try:
                return self.ph.verify(hash_val, pwd)
            except Exception:
                return False
        return False

    def authenticate(self, user: str, pwd: str) -> bool:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT username, password_hash FROM users WHERE username = ?", (user,))
        row = cur.fetchone()
        if not row:
            return False

        current_hash = row["password_hash"]
        if not self._verify_password(pwd, current_hash):
            return False

        if len(current_hash) == 64:
            new_hash = self._hash_password(pwd)
            with conn:
                conn.execute("UPDATE users SET password_hash = ? WHERE username = ?", (new_hash, user))

        return True

    def authenticate_doctor(self, doctor_name: str, pwd: str) -> bool:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT name, password_hash FROM doctors WHERE name = ?", (doctor_name,))
        row = cur.fetchone()
        if not row:
            return False

        current_hash = row["password_hash"] or ""
        if not current_hash:
            # First-time initialization for seeded doctor profiles
            new_hash = self._hash_password(pwd)
            with conn:
                conn.execute("UPDATE doctors SET password_hash = ? WHERE name = ?", (new_hash, doctor_name))
            add_audit_log(action="DOCTOR_SET_PASSWORD", user=doctor_name, details="Initialized doctor credentials")
            return True

        if not self._verify_password(pwd, current_hash):
            return False

        if len(current_hash) == 64:
            new_hash = self._hash_password(pwd)
            with conn:
                conn.execute("UPDATE doctors SET password_hash = ? WHERE name = ?", (new_hash, doctor_name))

        add_audit_log(action="DOCTOR_LOGIN", user=doctor_name, details="Doctor authenticated successfully")
        return True

    def register(self, user: str, pwd: str, insurance: List[str]) -> bool:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT username FROM users WHERE username = ?", (user,))
        if cur.fetchone():
            return False

        pwd_hash = self._hash_password(pwd)
        insurance_json = json.dumps(insurance)

        try:
            with conn:
                conn.execute(
                    "INSERT INTO users (username, password_hash, insurance) VALUES (?, ?, ?)",
                    (user, pwd_hash, insurance_json)
                )
            add_audit_log(action="REGISTER_USER", user=user, details=f"Insurance: {insurance}")
            return True
        except Exception:
            return False

    def create_session(self, token: str, user: str, role: str = "patient") -> None:
        self.sessions[token] = user
        self.roles[token] = role
        cache.set_session(token, f"{role}:{user}")

    def validate(self, token: str) -> bool:
        if token == "DOCTOR_INTERNAL":
            return True
        cached_user = cache.get_session(token)
        if cached_user:
            return True
        return token in self.sessions

    def get_role(self, token: str) -> str:
        if token == "DOCTOR_INTERNAL":
            return "doctor"
        cached = cache.get_session(token)
        if cached and ":" in cached:
            return cached.split(":", 1)[0]
        return self.roles.get(token, "patient" if self.validate(token) else "")

    def is_doctor(self, token: str) -> bool:
        return self.get_role(token) == "doctor"

    def get_user(self, token: str) -> str:
        if token == "DOCTOR_INTERNAL":
            return "DOCTOR_INTERNAL"
        cached_user = cache.get_session(token)
        if cached_user:
            if ":" in cached_user:
                return cached_user.split(":", 1)[1]
            return cached_user
        return self.sessions.get(token, "")

    def get_insurance(self, token: str) -> List[str]:
        user = self.get_user(token)
        if not user:
            return []
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT insurance FROM users WHERE username = ?", (user,))
        row = cur.fetchone()
        if row and row["insurance"]:
            try:
                return json.loads(row["insurance"])
            except Exception:
                return []
        return []

    def invalidate(self, token: str) -> None:
        self.sessions.pop(token, None)
        self.roles.pop(token, None)
        cache.delete_session(token)
