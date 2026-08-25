import json
import os
import hashlib
from typing import Dict, List, Optional
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, VerificationError
from db import get_db_connection, init_db, add_audit_log


class AuthManager:

    def __init__(self):
        init_db()
        self.ph = PasswordHasher()
        self.sessions: Dict[str, str] = {}

    def _hash_password(self, pwd: str) -> str:
        return self.ph.hash(pwd)

    def _verify_password(self, pwd: str, hash_val: str) -> bool:
        if not hash_val:
            return False
        # Check if legacy SHA-256 hash (64 hex characters)
        if len(hash_val) == 64 and all(c in "0123456789abcdefABCDEF" for c in hash_val):
            sha_matches = hashlib.sha256(pwd.encode()).hexdigest() == hash_val
            return sha_matches

        try:
            return self.ph.verify(hash_val, pwd)
        except (VerifyMismatchError, VerificationError, Exception):
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

        # Upgrade legacy hash to Argon2id if needed
        if len(current_hash) == 64:
            new_hash = self._hash_password(pwd)
            with conn:
                conn.execute("UPDATE users SET password_hash = ? WHERE username = ?", (new_hash, user))

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

    def create_session(self, token: str, user: str) -> None:
        self.sessions[token] = user

    def validate(self, token: str) -> bool:
        return token in self.sessions

    def get_user(self, token: str) -> str:
        return self.sessions.get(token, "")

    def get_insurance(self, token: str) -> List[str]:
        user = self.sessions.get(token, "")
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
