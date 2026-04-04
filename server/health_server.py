import socket
import threading
import json
import uuid
import sys
import os
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from scheduler import Scheduler
from auth import AuthManager
from logger import log
from queue_manager import QueueManager
from chat_history import ChatHistory

HOST = "127.0.0.1"
PORT = 4000

auth = AuthManager()
scheduler = Scheduler()
queue_mgr = QueueManager()
chat_hist = ChatHistory()

_start_time = time.time()

_stats_lock = threading.Lock()
_stats = {
    "total_logins": 0,
    "total_bookings": 0,
    "total_chats": 0,
}

class RateLimiter:
    def __init__(self, rate: float = 10.0, capacity: float = 20.0, ban_time: float = 300.0):
        self.rate = rate
        self.capacity = capacity
        self.ban_time = ban_time
        self.tokens = {}
        self.last_ts = {}
        self.banned = {}
        self._lock = threading.Lock()

    def allow(self, ip: str) -> bool:
        with self._lock:
            now = time.time()
            if ip in self.banned:
                if now - self.banned[ip] < self.ban_time:
                    return False
                else:
                    del self.banned[ip]

            tokens = self.tokens.get(ip, self.capacity)
            last = self.last_ts.get(ip, now)
            
            elapsed = now - last
            tokens = min(self.capacity, tokens + elapsed * self.rate)
            
            if tokens >= 1.0:
                self.tokens[ip] = tokens - 1.0
                self.last_ts[ip] = now
                return True
            else:
                self.banned[ip] = now
                self.tokens[ip] = self.capacity
                return False

    def get_banned_ips(self) -> list:
        with self._lock:
            now = time.time()
            return [ip for ip, ts in list(self.banned.items()) if now - ts < self.ban_time]
            
    def unban(self, ip: str) -> bool:
        with self._lock:
            if ip in self.banned:
                del self.banned[ip]
                return True
            return False

rate_limiter = RateLimiter()

_active_subs_lock = threading.Lock()
_active_subs = []


def _incr(key: str) -> None:
    with _stats_lock:
        _stats[key] += 1


def send(conn: socket.socket, payload: dict) -> None:
    conn.sendall((json.dumps(payload) + "\n").encode())


def _broadcast_to_subs(payload: dict) -> None:
    with _active_subs_lock:
        to_remove = []
        for sub in _active_subs:
            try:
                send(sub, payload)
            except Exception:
                to_remove.append(sub)
        for sub in to_remove:
            if sub in _active_subs:
                _active_subs.remove(sub)


def recv_line(conn: socket.socket, buf_size: int = 8192) -> str | None:
    data = b""
    while True:
        chunk = conn.recv(buf_size)
        if not chunk:
            return None
        data += chunk
        if b"\n" in data:
            return data.split(b"\n", 1)[0].decode()


def handle_client(conn: socket.socket, addr: tuple) -> None:
    try:
        _client_loop(conn, addr)
    except ConnectionError:
        pass
    except Exception as exc:
        log(f"[ERROR] handle_client({addr}): {exc}")
    finally:
        conn.close()


def handle_login(conn, request):
    user = request.get("username", "")
    pwd = request.get("password", "")

    if auth.authenticate(user, pwd):
        token = str(uuid.uuid4())
        auth.create_session(token, user)
        _incr("total_logins")
        log(f"LOGIN OK: {user}")
        insurances = auth.users[user].get("insurance", [])
        send(conn, {"status": "OK", "token": token, "insurance": insurances})
    else:
        log(f"LOGIN FAIL: {user}")
        send(conn, {"status": "FAIL", "reason": "Invalid credentials"})
        
def handle_register(conn, request):
    user = request.get("username", "")
    pwd = request.get("password", "")
    insurance = request.get("insurance", [])
    
    if auth.register(user, pwd, insurance):
        token = str(uuid.uuid4())
        auth.create_session(token, user)
        _incr("total_logins")
        log(f"REGISTER OK: {user}")
        send(conn, {"status": "OK", "token": token, "insurance": insurance})
    else:
        log(f"REGISTER FAIL (user exists): {user}")
        send(conn, {"status": "FAIL", "reason": "Username already taken"})

def handle_get_specializations(conn, request, token):
    all_docs = scheduler.get_all_doctors()
    online_specs = {
        info.get("specialization", "General")
        for doc, info in all_docs.items()
        if queue_mgr.is_online(doc)
    }
    all_specs = {info.get("specialization", "General") for info in all_docs.values()}
    
    sorted_specs = sorted(list(all_specs), key=lambda s: (s not in online_specs, s))
    send(conn, {"status": "OK", "specializations": sorted_specs})

def handle_get_slots(conn, request, token):
    insurance = auth.get_insurance(token)
    specialization = request.get("specialization")
    slots = scheduler.get_slots(insurance, specialization)
    send(conn, slots)

def handle_book_slot(conn, request, token):
    doctor = request.get("doctor", "")
    slot = request.get("slot", "")
    user = auth.get_user(token)
    result = scheduler.book_slot(user, doctor, slot)

    if result["status"] == "BOOKED":
        _incr("total_bookings")
        log(f"BOOKED: {user} → {doctor} @ {slot}")

    send(conn, result)

def handle_get_my_appointments(conn, request, token):
    user = auth.get_user(token)
    appointments = scheduler.get_bookings_for_patient(user)
    send(conn, {"status": "OK", "appointments": appointments})

def handle_cancel_my_booking(conn, request, token):
    user = auth.get_user(token)
    doctor = request.get("doctor", "")
    slot = request.get("slot", "")

    result = scheduler.remove_booking_for_patient(user, doctor, slot)
    if result.get("status") == "OK":
        log(f"PATIENT_CANCEL: {user} cancelled {doctor} @ {slot}")
    send(conn, result)

def handle_request_chat(conn, request, token):
    doctor = request.get("doctor", "")
    user = auth.get_user(token)
    doctors_data = scheduler.get_all_doctors()

    if doctor not in doctors_data:
        send(conn, {"status": "FAIL", "reason": "Doctor not found"})
        return

    if not queue_mgr.is_online(doctor):
        send(conn, {"status": "FAIL", "reason": "Doctor is currently offline."})
        return

    udp_port = doctors_data[doctor]["udp_port"]

    if queue_mgr.try_start_session(doctor, user):
        log(f"REQUEST_CHAT: Granted immediately {user} → {doctor}")
        send(conn, {
            "status": "READY",
            "udp_port": udp_port,
            "doctor": doctor,
        })
    else:
        pos = queue_mgr.enqueue(doctor, user, conn)
        send(conn, {
            "status": "QUEUED",
            "position": pos,
            "doctor": doctor,
            "message": f"Doctor is busy. You are #{pos} in queue.",
        })

def handle_start_chat(conn, request, token):
    doctor = request.get("doctor", "")
    session_id = request.get("session_id", str(uuid.uuid4()))
    user = auth.get_user(token)
    chat_hist.start_session(session_id, doctor, user)
    _incr("total_chats")
    log(f"START_CHAT: {user} ↔ {doctor}  [session={session_id}]")
    send(conn, {"status": "CHAT_LOGGED", "session_id": session_id})

def handle_log_message(conn, request, token):
    session_id = request.get("session_id", "")
    sender = request.get("sender", "")
    text = request.get("text", "")
    session = chat_hist.get_session(session_id)
    if session:
        session.log_message(sender, text)
    send(conn, {"status": "OK"})

def handle_terminate_chat(conn, request, token):
    doctor = request.get("doctor", "")
    session_id = request.get("session_id", "")
    user = auth.get_user(token)
    chat_hist.end_session(session_id, reason="CLIENT_TERMINATED")
    log(f"TERMINATE_CHAT: {user} ↔ {doctor}  [session={session_id}]")
    send(conn, {"status": "CHAT_TERMINATED_LOGGED"})

def handle_end_session(conn, request, token):
    doctor = request.get("doctor", "")
    session_id = request.get("session_id", "")
    is_doctor = (token == "DOCTOR_INTERNAL")
    user = auth.get_user(token) if not is_doctor else doctor
    chat_hist.end_session(session_id, reason="NORMAL")
    log(f"END_SESSION: {doctor} now free (triggered by {user})")

    while True:
        next_patient = queue_mgr.end_session(doctor)
        if not next_patient:
            break
        next_user, next_conn = next_patient
        doctors_data = scheduler.get_all_doctors()
        udp_port = doctors_data[doctor]["udp_port"]
        log(f"QUEUE: Notifying next patient {next_user} → {doctor}")
        try:
            send(next_conn, {
                "status": "TURN_READY",
                "udp_port": udp_port,
                "doctor": doctor,
                "message": "Doctor is now available. Connecting you...",
            })
            break
        except Exception as e:
            log(f"[WARN] Could not notify {next_user}: {e}. Trying next in queue...")

    send(conn, {"status": "SESSION_ENDED"})

def handle_cancel_queue(conn, request, token):
    doctor = request.get("doctor", "")
    user = auth.get_user(token)
    queue_mgr.remove_from_queue(doctor, user)
    send(conn, {"status": "QUEUE_CANCELLED"})
    log(f"CANCEL_QUEUE: {user} left queue for {doctor}")

def handle_dashboard(conn, request):
    snap = queue_mgr.snapshot()
    with _stats_lock:
        stats_copy = dict(_stats)
    stats_copy["uptime"] = int(time.time() - _start_time)
    send(conn, {
        "status": "OK",
        "queue_state": snap,
        "stats": stats_copy,
        "banned_ips": rate_limiter.get_banned_ips()
    })

def handle_admin_get_bookings(conn, request):
    bookings = scheduler.get_all_bookings()
    send(conn, {"status": "OK", "bookings": bookings})

def handle_admin_remove_booking(conn, request):
    doctor = request.get("doctor", "")
    slot = request.get("slot", "")
    if scheduler.remove_booking(doctor, slot):
        send(conn, {"status": "OK"})
        log(f"ADMIN: Removed booking {slot} for {doctor}")
    else:
        send(conn, {"status": "FAIL", "reason": "Booking not found"})

def handle_doctor_online(conn, request, token):
    if token != "DOCTOR_INTERNAL":
        send(conn, {"status": "INVALID_SESSION"})
        return
    doctor = request.get("doctor", "")
    queue_mgr.set_online(doctor, True)
    log(f"LOGIN OK (DOCTOR): {doctor} is now ONLINE")
    send(conn, {"status": "OK"})

def handle_doctor_offline(conn, request, token):
    if token != "DOCTOR_INTERNAL":
        send(conn, {"status": "INVALID_SESSION"})
        return
    doctor = request.get("doctor", "")
    queue_mgr.set_online(doctor, False)
    log(f"LOGOUT (DOCTOR): {doctor} is now OFFLINE")
    send(conn, {"status": "OK"})

def handle_get_doctors(conn, request, token):
    insurance = auth.get_insurance(token)
    all_docs = scheduler.get_all_doctors()
    augmented_docs = {}
    for doc_name, doc_info in all_docs.items():
        if not any(i in doc_info.get("accepted_insurance", []) for i in insurance):
            continue
        info_copy = doc_info.copy()
        info_copy["online"] = queue_mgr.is_online(doc_name)
        augmented_docs[doc_name] = info_copy
    send(conn, {"status": "OK", "doctors": augmented_docs})

def handle_admin_banned_ips(conn, request):
    send(conn, {"status": "OK", "banned_ips": rate_limiter.get_banned_ips()})

def handle_admin_unban_ip(conn, request):
    ip = request.get("ip", "")
    if rate_limiter.unban(ip):
        send(conn, {"status": "OK"})
        log(f"ADMIN: Unbanned IP {ip}")
    else:
        send(conn, {"status": "FAIL", "reason": "IP not found in ban list"})

def handle_subscribe(conn, request):
    try:
        with _active_subs_lock:
            _active_subs.append(conn)
        while True:
            d = conn.recv(1024)
            if not d: break
    except ConnectionError:
        pass
    finally:
        with _active_subs_lock:
            if conn in _active_subs:
                _active_subs.remove(conn)

def handle_admin_global_msg(conn, request):
    msg = request.get("message", "")
    _broadcast_to_subs({"status": "GLOBAL_MSG", "message": msg})
    send(conn, {"status": "OK"})

def handle_admin_kill_session(conn, request):
    session_id = request.get("session_id", "")
    _broadcast_to_subs({"status": "KILL_SESSION", "session_id": session_id})
    send(conn, {"status": "OK"})


COMMAND_HANDLERS = {
    "LOGIN": (handle_login, False),
    "REGISTER": (handle_register, False),
    "DASHBOARD": (handle_dashboard, False),
    "ADMIN_GET_BOOKINGS": (handle_admin_get_bookings, False),
    "ADMIN_REMOVE_BOOKING": (handle_admin_remove_booking, False),
    "ADMIN_BANNED_IPS": (handle_admin_banned_ips, False),
    "ADMIN_UNBAN_IP": (handle_admin_unban_ip, False),
    "SUBSCRIBE": (handle_subscribe, False),
    "ADMIN_GLOBAL_MSG": (handle_admin_global_msg, False),
    "ADMIN_KILL_SESSION": (handle_admin_kill_session, False),
    
    "GET_SPECIALIZATIONS": (handle_get_specializations, True),
    "GET_SLOTS": (handle_get_slots, True),
    "BOOK_SLOT": (handle_book_slot, True),
    "GET_MY_APPOINTMENTS": (handle_get_my_appointments, True),
    "CANCEL_MY_BOOKING": (handle_cancel_my_booking, True),
    "REQUEST_CHAT": (handle_request_chat, True),
    "START_CHAT": (handle_start_chat, True),
    "LOG_MESSAGE": (handle_log_message, True),
    "TERMINATE_CHAT": (handle_terminate_chat, True),
    "END_SESSION": (handle_end_session, True),
    "CANCEL_QUEUE": (handle_cancel_queue, True),
    "DOCTOR_ONLINE": (handle_doctor_online, True),
    "DOCTOR_OFFLINE": (handle_doctor_offline, True),
    "GET_DOCTORS": (handle_get_doctors, True),
}

def _client_loop(conn: socket.socket, addr: tuple) -> None:
    ip = addr[0]
    while True:
        raw = recv_line(conn)
        if raw is None:
            break

        if not rate_limiter.allow(ip):
            send(conn, {"status": "FAIL", "reason": "BANNED: Rate limit exceeded."})
            log(f"[WARN] IP {ip} rate limited and temporarily banned.")
            return

        try:
            request = json.loads(raw)
        except json.JSONDecodeError:
            send(conn, {"status": "BAD_REQUEST", "reason": "Invalid JSON"})
            continue

        command = request.get("command", "")
        if command not in COMMAND_HANDLERS:
            send(conn, {"status": "UNKNOWN_COMMAND", "command": command})
            continue
            
        handler, requires_auth = COMMAND_HANDLERS[command]
        
        if requires_auth:
            token = request.get("token", "")
            is_doctor_internal = (token == "DOCTOR_INTERNAL")
            if not is_doctor_internal and not auth.validate(token):
                send(conn, {"status": "INVALID_SESSION"})
                continue
            handler(conn, request, token)
        else:
            handler(conn, request)



def main():
    server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server_sock.bind((HOST, PORT))
    server_sock.listen(64)

    log(f"=== Health Center Server started on {HOST}:{PORT} ===")

    while True:
        conn, addr = server_sock.accept()
        t = threading.Thread(target=handle_client, args=(conn, addr), daemon=True)
        t.start()


if __name__ == "__main__":
    main()
