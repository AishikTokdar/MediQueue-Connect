import threading
import collections
from logger import log


class QueueManager:

    def __init__(self):
        self._lock = threading.RLock()
        self._busy: dict[str, bool] = {}
        self._queues: dict[str, collections.deque] = {}
        self._active_patient: dict[str, str] = {}
        self._position_cache: dict[tuple, int] = {}
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
            self._queues[doctor] = collections.deque()

    def _recompute_positions(self, doctor: str) -> None:
        for idx, (user, _conn) in enumerate(self._queues[doctor], start=1):
            self._position_cache[(doctor, user)] = idx

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

    def enqueue(self, doctor: str, username: str, conn=None) -> int:
        with self._lock:
            self._ensure_doctor(doctor)
            self._queues[doctor].append((username, conn))
            self._recompute_positions(doctor)
            pos = self._position_cache[(doctor, username)]
            log(f"[QUEUE] {username} waiting for {doctor} at position {pos}")
            return pos

    def get_queue(self, doctor: str) -> list[str]:
        with self._lock:
            self._ensure_doctor(doctor)
            return [u for u, _ in self._queues[doctor]]

    def get_all_queues(self) -> dict[str, list[str]]:
        with self._lock:
            return {doc: [u for u, _ in q] for doc, q in self._queues.items()}

    def dequeue_patient(self, doctor: str, username: str) -> bool:
        with self._lock:
            self._ensure_doctor(doctor)
            initial_len = len(self._queues[doctor])
            self._queues[doctor] = collections.deque(
                (u, c) for u, c in self._queues[doctor] if u != username
            )
            self._position_cache.pop((doctor, username), None)
            self._recompute_positions(doctor)
            return len(self._queues[doctor]) < initial_len

    def dequeue_next(self, doctor: str) -> str | None:
        next_item = self.end_session(doctor)
        if next_item:
            return next_item[0] if isinstance(next_item, tuple) else next_item
        return None

    def end_session(self, doctor: str) -> tuple | None:
        with self._lock:
            self._ensure_doctor(doctor)
            self._busy[doctor] = False
            prev = self._active_patient.pop(doctor, None)
            log(f"[QUEUE] Session ENDED for {doctor} (was: {prev})")

            if self._queues[doctor]:
                next_patient = self._queues[doctor].popleft()
                username, conn = next_patient
                self._position_cache.pop((doctor, username), None)
                self._recompute_positions(doctor)
                self._busy[doctor] = True
                self._active_patient[doctor] = username
                log(f"[QUEUE] Next patient {username} now active with {doctor}")
                return next_patient
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

    def snapshot(self) -> dict:
        with self._lock:
            return {
                doc: {
                    "online": doc in self._online_doctors,
                    "busy": self._busy.get(doc, False),
                    "active_patient": self._active_patient.get(doc),
                    "queue": [u for u, _ in self._queues.get(doc, [])],
                }
                for doc in set(list(self._busy.keys()) + list(self._queues.keys())) | self._online_doctors
            }

