import threading
import time
from typing import Any, Dict, List, Optional, Tuple
from logger import log


ESI_LEVELS = {
    1: "Resuscitation / Immediate",
    2: "Emergent",
    3: "Urgent",
    4: "Less Urgent",
    5: "Non-Urgent / Routine",
}


class QueueEntry:
    def __init__(self, username: str, esi_level: int = 5, arrival_time: Optional[float] = None, conn: Any = None):
        self.username = username
        self.esi_level = max(1, min(5, int(esi_level)))
        self.arrival_time = arrival_time or time.time()
        self.conn = conn

    def score(self, now: float) -> float:
        # Effective score: lower is higher priority.
        # Aging mechanism: for every 60 seconds waiting, score reduces by 0.25 (anti-starvation)
        wait_secs = max(0.0, now - self.arrival_time)
        age_bonus = (wait_secs / 60.0) * 0.25
        return self.esi_level - age_bonus


class QueueManager:

    def __init__(self):
        self._lock = threading.RLock()
        self._busy: Dict[str, bool] = {}
        self._queues: Dict[str, List[QueueEntry]] = {}
        self._active_patient: Dict[str, str] = {}
        self._position_cache: Dict[Tuple[str, str], int] = {}
        self._online_doctors: set[str] = set()

    def set_online(self, doctor: str, is_online: bool) -> None:
        with self._lock:
            self._ensure_doctor(doctor)
            if is_online:
                self._online_doctors.add(doctor)
            else:
                self._online_doctors.discard(doctor)

    def is_online(self, doctor: str) -> bool:
        with self._lock:
            return doctor in self._online_doctors

    def _ensure_doctor(self, doctor: str) -> None:
        if doctor not in self._busy:
            self._busy[doctor] = False
            self._queues[doctor] = []

    def _sort_and_recompute(self, doctor: str) -> None:
        now = time.time()
        self._queues[doctor].sort(key=lambda e: (e.score(now), e.arrival_time))
        for idx, entry in enumerate(self._queues[doctor], start=1):
            self._position_cache[(doctor, entry.username)] = idx

    def is_busy(self, doctor: str) -> bool:
        with self._lock:
            self._ensure_doctor(doctor)
            return self._busy[doctor]

    def try_start_session(self, doctor: str, username: str) -> bool:
        with self._lock:
            self._ensure_doctor(doctor)
            if self._busy[doctor]:
                return False
            self._busy[doctor] = True
            self._active_patient[doctor] = username
            log(f"[QUEUE] Session STARTED: {username} <-> {doctor}")
            return True

    def enqueue(self, doctor: str, username: str, esi_level: int = 5, conn=None) -> int:
        with self._lock:
            self._ensure_doctor(doctor)
            existing = next((e for e in self._queues[doctor] if e.username == username), None)
            if existing:
                if esi_level < existing.esi_level:
                    existing.esi_level = esi_level
            else:
                entry = QueueEntry(username=username, esi_level=esi_level, conn=conn)
                self._queues[doctor].append(entry)

            self._sort_and_recompute(doctor)
            pos = self._position_cache.get((doctor, username), 1)
            desc = ESI_LEVELS.get(esi_level, "Routine")
            log(f"[QUEUE] {username} queued for {doctor} [ESI-{esi_level}: {desc}] at position {pos}")
            return pos

    def get_queue(self, doctor: str) -> List[str]:
        with self._lock:
            self._ensure_doctor(doctor)
            self._sort_and_recompute(doctor)
            return [e.username for e in self._queues[doctor]]

    def get_queue_details(self, doctor: str) -> List[Dict[str, Any]]:
        with self._lock:
            self._ensure_doctor(doctor)
            self._sort_and_recompute(doctor)
            now = time.time()
            return [
                {
                    "patient": e.username,
                    "esi_level": e.esi_level,
                    "esi_desc": ESI_LEVELS.get(e.esi_level, "Routine"),
                    "wait_time_sec": round(now - e.arrival_time, 1),
                    "priority_score": round(e.score(now), 2),
                }
                for e in self._queues[doctor]
            ]

    def get_all_queues(self) -> Dict[str, List[str]]:
        with self._lock:
            return {doc: [e.username for e in q] for doc, q in self._queues.items()}

    def dequeue_patient(self, doctor: str, username: str) -> bool:
        with self._lock:
            self._ensure_doctor(doctor)
            initial_len = len(self._queues[doctor])
            self._queues[doctor] = [e for e in self._queues[doctor] if e.username != username]
            self._position_cache.pop((doctor, username), None)
            self._sort_and_recompute(doctor)
            return len(self._queues[doctor]) < initial_len

    def dequeue_next(self, doctor: str) -> Optional[str]:
        next_item = self.end_session(doctor)
        if next_item:
            return next_item[0] if isinstance(next_item, tuple) else next_item
        return None

    def end_session(self, doctor: str) -> Optional[Tuple[str, Any, int]]:
        with self._lock:
            self._ensure_doctor(doctor)
            self._busy[doctor] = False
            prev = self._active_patient.pop(doctor, None)
            log(f"[QUEUE] Session ENDED for {doctor} (was: {prev})")

            if self._queues[doctor]:
                self._sort_and_recompute(doctor)
                entry = self._queues[doctor].pop(0)
                self._position_cache.pop((doctor, entry.username), None)
                self._sort_and_recompute(doctor)
                self._busy[doctor] = True
                self._active_patient[doctor] = entry.username
                desc = ESI_LEVELS.get(entry.esi_level, "Routine")
                log(f"[QUEUE] Next patient {entry.username} [ESI-{entry.esi_level}: {desc}] now active with {doctor}")
                return (entry.username, entry.conn, entry.esi_level)
            return None

    def remove_from_queue(self, doctor: str, username: str) -> None:
        self.dequeue_patient(doctor, username)

    def queue_position(self, doctor: str, username: str) -> int:
        with self._lock:
            return self._position_cache.get((doctor, username), 0)

    def queue_length(self, doctor: str) -> int:
        with self._lock:
            self._ensure_doctor(doctor)
            return len(self._queues[doctor])

    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            return {
                doc: {
                    "online": doc in self._online_doctors,
                    "busy": self._busy.get(doc, False),
                    "active_patient": self._active_patient.get(doc),
                    "queue": [e.username for e in self._queues.get(doc, [])],
                }
                for doc in set(list(self._busy.keys()) + list(self._queues.keys())) | self._online_doctors
            }
