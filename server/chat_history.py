import json
import os
import threading
from datetime import datetime


_HISTORY_ROOT = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "data", "chat_history"
)


class ChatSession:

    def __init__(self, session_id: str, doctor: str, patient: str):
        self.session_id = session_id
        self.doctor = doctor
        self.patient = patient
        self._lock = threading.Lock()

        doctor_dir = os.path.join(_HISTORY_ROOT, doctor)
        os.makedirs(doctor_dir, exist_ok=True)

        self._path = os.path.join(doctor_dir, f"{session_id}.jsonl")
        self._write({
            "event": "SESSION_START",
            "doctor": doctor,
            "patient": patient,
        })

    def _write(self, record: dict) -> None:
        record["ts"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        with self._lock:
            with open(self._path, "a", encoding="utf-8") as f:
                f.write(json.dumps(record) + "\n")

    def log_message(self, sender: str, text: str) -> None:
        self._write({"sender": sender, "text": text})

    def close(self, reason: str = "NORMAL") -> None:
        self._write({"event": "SESSION_END", "reason": reason})

    @property
    def path(self) -> str:
        return self._path


class ChatHistory:

    def __init__(self):
        os.makedirs(_HISTORY_ROOT, exist_ok=True)
        self._sessions: dict[str, ChatSession] = {}
        self._lock = threading.Lock()

    def start_session(self, session_id: str, doctor: str, patient: str) -> ChatSession:
        session = ChatSession(session_id, doctor, patient)
        with self._lock:
            self._sessions[session_id] = session
        return session

    def get_session(self, session_id: str) -> ChatSession | None:
        with self._lock:
            return self._sessions.get(session_id)

    def end_session(self, session_id: str, reason: str = "NORMAL") -> None:
        with self._lock:
            session = self._sessions.pop(session_id, None)
        if session:
            session.close(reason)

    def sync_transcript(self, session_id: str, doctor: str, patient: str, messages: list[dict], reason: str = "NORMAL") -> str:
        """
        Synchronizes consultation dialogue messages to disk. If the session is active,
        logs remaining messages; otherwise creates/updates the session transcript file.
        Returns the absolute filepath to the JSONL log.
        """
        with self._lock:
            self._sessions.pop(session_id, None)

        doctor_dir = os.path.join(_HISTORY_ROOT, doctor)
        os.makedirs(doctor_dir, exist_ok=True)
        path = os.path.join(doctor_dir, f"{session_id}.jsonl")

        file_exists = os.path.exists(path) and os.path.getsize(path) > 0
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]

        with open(path, "a", encoding="utf-8") as f:
            if not file_exists:
                f.write(json.dumps({"event": "SESSION_START", "doctor": doctor, "patient": patient, "ts": now_str}) + "\n")
            for msg in messages:
                m_rec = {
                    "sender": msg.get("sender", "peer"),
                    "text": msg.get("text", ""),
                    "ts": msg.get("ts") or now_str,
                }
                f.write(json.dumps(m_rec) + "\n")
            f.write(json.dumps({"event": "SESSION_END", "reason": reason, "ts": now_str}) + "\n")

        return path
