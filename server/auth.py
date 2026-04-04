import json
import os
import hashlib


class AuthManager:

    def __init__(self):
        self.data_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "users.json")
        with open(self.data_path) as f:
            self.users = json.load(f)
        self.sessions: dict[str, str] = {}

    def authenticate(self, user: str, pwd: str) -> bool:
        if user not in self.users:
            return False
        return self.users[user]["password"] == hashlib.sha256(pwd.encode()).hexdigest()

    def register(self, user: str, pwd: str, insurance: list) -> bool:
        if user in self.users:
            return False
        self.users[user] = {
            "password": hashlib.sha256(pwd.encode()).hexdigest(),
            "insurance": insurance
        }
        with open(self.data_path, "w") as f:
            json.dump(self.users, f, indent=4)
        return True

    def create_session(self, token: str, user: str) -> None:
        self.sessions[token] = user

    def validate(self, token: str) -> bool:
        return token in self.sessions

    def get_user(self, token: str) -> str:
        return self.sessions.get(token, "")

    def get_insurance(self, token: str) -> list:
        user = self.sessions.get(token, "")
        return self.users.get(user, {}).get("insurance", [])

    def invalidate(self, token: str) -> None:
        self.sessions.pop(token, None)
