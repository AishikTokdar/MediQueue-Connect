import asyncio
import json
import os
import signal
import socket
import sys
import time
import uuid
from typing import Any, Dict, List, Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from auth import AuthManager
from chat_history import ChatHistory
from crypto_utils import get_server_ssl_context
from db import get_audit_logs, init_db
from logger import log, log_audit
from protocol import async_recv_framed, async_send_framed
from queue_manager import QueueManager
from scheduler import Scheduler
from schemas import validate_request_payload

HOST = "127.0.0.1"
PORT = 4000

init_db()

auth = AuthManager()
scheduler = Scheduler()
queue_mgr = QueueManager()
chat_hist = ChatHistory()

_start_time = time.time()
_stats_lock = asyncio.Lock()
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
        self.tokens: Dict[str, float] = {}
        self.last_ts: Dict[str, float] = {}
        self.banned: Dict[str, float] = {}
        self._lock = asyncio.Lock()

    async def allow(self, ip: str) -> bool:
        async with self._lock:
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

    async def get_banned_ips(self) -> List[str]:
        async with self._lock:
            now = time.time()
            return [ip for ip, ts in list(self.banned.items()) if now - ts < self.ban_time]
            
    async def unban(self, ip: str) -> bool:
        async with self._lock:
            if ip in self.banned:
                del self.banned[ip]
                return True
            return False


rate_limiter = RateLimiter()

_active_subs_lock = asyncio.Lock()
_active_subs: List[asyncio.StreamWriter] = []
_is_shutting_down = False


async def _incr_stat(key: str) -> None:
    async with _stats_lock:
        _stats[key] += 1


async def _broadcast_to_subs(payload: Dict[str, Any]) -> None:
    async with _active_subs_lock:
        to_remove = []
        for writer in _active_subs:
            try:
                await async_send_framed(writer, payload)
            except Exception:
                to_remove.append(writer)
        for w in to_remove:
            if w in _active_subs:
                _active_subs.remove(w)


async def handle_client(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    peer_info = writer.get_extra_info("peername")
    client_ip = peer_info[0] if peer_info else "unknown"

    while not _is_shutting_down:
        if not await rate_limiter.allow(client_ip):
            log(f"IP {client_ip} rate limited & banned", level="WARN", client_ip=client_ip)
            await async_send_framed(writer, {"status": "ERROR", "reason": "Rate limit exceeded. Temporary IP ban."})
            break

        data = await async_recv_framed(reader)
        if data is None:
            break

        trace_id = str(uuid.uuid4())[:8]
        cmd = data.get("command", "")
        log(f"Received command: {cmd}", level="INFO", trace_id=trace_id, client_ip=client_ip)

        # Validate input schema
        is_valid, err_msg, validated_payload = validate_request_payload(cmd, data)
        if not is_valid:
            log(f"Invalid payload for {cmd}: {err_msg}", level="WARN", trace_id=trace_id)
            await async_send_framed(writer, {"status": "ERROR", "reason": err_msg})
            continue

        resp = await process_command(cmd, data, client_ip, trace_id, writer)
        if resp is not None:
            await async_send_framed(writer, resp)

    # Cleanup sub if subscribed
    async with _active_subs_lock:
        if writer in _active_subs:
            _active_subs.remove(writer)

    writer.close()
    try:
        await writer.wait_closed()
    except Exception:
        pass


async def process_command(cmd: str, data: Dict[str, Any], client_ip: str, trace_id: str, writer: asyncio.StreamWriter) -> Optional[Dict[str, Any]]:
    if cmd == "LOGIN":
        username = data.get("username", "")
        password = data.get("password", "")
        if auth.authenticate(username, password):
            token = str(uuid.uuid4())
            auth.create_session(token, username)
            await _incr_stat("total_logins")
            log_audit("USER_LOGIN", user=username, trace_id=trace_id, details=f"IP: {client_ip}")
            return {"status": "OK", "token": token, "username": username}
        else:
            log("Login failed", level="WARN", trace_id=trace_id, client_ip=client_ip)
            return {"status": "FAIL", "reason": "Invalid credentials"}

    elif cmd == "REGISTER":
        username = data.get("username", "")
        password = data.get("password", "")
        insurance = data.get("insurance", [])
        if auth.register(username, password, insurance):
            log_audit("USER_REGISTER", user=username, trace_id=trace_id)
            return {"status": "OK"}
        else:
            return {"status": "FAIL", "reason": "Username already exists"}

    elif cmd == "GET_SLOTS":
        token = data.get("token", "")
        if not auth.validate(token):
            return {"status": "ERROR", "reason": "Invalid token"}
        user_insurance = auth.get_insurance(token)
        specialization = data.get("specialization")
        slots = scheduler.get_slots(user_insurance, specialization)
        return {"status": "OK", "doctors": slots}

    elif cmd == "BOOK":
        token = data.get("token", "")
        if not auth.validate(token):
            return {"status": "ERROR", "reason": "Invalid token"}
        user = auth.get_user(token)
        doctor = data.get("doctor", "")
        slot = data.get("slot", "")
        resp = scheduler.book_slot(user, doctor, slot)
        if resp.get("status") == "BOOKED":
            await _incr_stat("total_bookings")
            log_audit("BOOK_APPOINTMENT", user=user, trace_id=trace_id, details=f"Doctor: {doctor}, Slot: {slot}")
        return resp

    elif cmd == "MY_BOOKINGS":
        token = data.get("token", "")
        if not auth.validate(token):
            return {"status": "ERROR", "reason": "Invalid token"}
        user = auth.get_user(token)
        bookings = scheduler.get_bookings_for_patient(user)
        return {"status": "OK", "bookings": bookings}

    elif cmd == "CANCEL_BOOKING":
        token = data.get("token", "")
        if not auth.validate(token):
            return {"status": "ERROR", "reason": "Invalid token"}
        user = auth.get_user(token)
        doctor = data.get("doctor", "")
        slot = data.get("slot", "")
        return scheduler.remove_booking_for_patient(user, doctor, slot)

    elif cmd == "JOIN_QUEUE":
        token = data.get("token", "")
        if not auth.validate(token):
            return {"status": "ERROR", "reason": "Invalid token"}
        user = auth.get_user(token)
        doctor = data.get("doctor", "")
        pos = queue_mgr.enqueue(doctor, user)
        log_audit("JOIN_QUEUE", user=user, trace_id=trace_id, details=f"Doctor: {doctor}, Pos: {pos}")
        return {"status": "QUEUED", "position": pos, "doctor": doctor}

    elif cmd == "LEAVE_QUEUE":
        token = data.get("token", "")
        if not auth.validate(token):
            return {"status": "ERROR", "reason": "Invalid token"}
        user = auth.get_user(token)
        doctor = data.get("doctor", "")
        success = queue_mgr.dequeue_patient(doctor, user)
        return {"status": "OK" if success else "FAIL"}

    elif cmd == "NEXT_PATIENT":
        token = data.get("token", "")
        if not auth.validate(token):
            return {"status": "ERROR", "reason": "Invalid token"}
        doctor = data.get("doctor", "")
        next_patient = queue_mgr.dequeue_next(doctor)
        if next_patient:
            await _incr_stat("total_chats")
            log_audit("NEXT_PATIENT", user=doctor, trace_id=trace_id, details=f"Patient: {next_patient}")
            return {"status": "OK", "next_patient": next_patient}
        return {"status": "EMPTY", "reason": "No patients in queue"}

    elif cmd == "GET_QUEUE":
        token = data.get("token", "")
        if not auth.validate(token):
            return {"status": "ERROR", "reason": "Invalid token"}
        doctor = data.get("doctor", "")
        q = queue_mgr.get_queue(doctor)
        return {"status": "OK", "queue": q}

    elif cmd == "GET_SPECIALIZATIONS":
        specs = scheduler.get_specializations()
        return {"status": "OK", "specializations": specs}

    elif cmd == "GET_STATS":
        banned = await rate_limiter.get_banned_ips()
        async with _stats_lock:
            st = dict(_stats)
        st["uptime_seconds"] = int(time.time() - _start_time)
        st["banned_ips"] = banned
        st["all_bookings"] = scheduler.get_all_bookings()
        st["all_queues"] = queue_mgr.get_all_queues()
        st["doctors"] = scheduler.get_all_doctors()
        return {"status": "OK", "stats": st}

    elif cmd == "SUBSCRIBE_STATS":
        async with _active_subs_lock:
            if writer not in _active_subs:
                _active_subs.append(writer)
        return {"status": "SUBSCRIBED"}

    elif cmd == "UNBAN_IP":
        ip = data.get("ip", "")
        unbanned = await rate_limiter.unban(ip)
        log_audit("UNBAN_IP", user="ADMIN", trace_id=trace_id, details=f"IP: {ip}")
        return {"status": "OK" if unbanned else "FAIL"}

    elif cmd == "CLEAR_BOOKING":
        doctor = data.get("doctor", "")
        slot = data.get("slot", "")
        success = scheduler.remove_booking(doctor, slot)
        return {"status": "OK" if success else "FAIL"}

    elif cmd == "AUDIT_LOGS":
        token = data.get("token", "")
        limit = data.get("limit", 50)
        logs = get_audit_logs(limit)
        return {"status": "OK", "logs": logs}

    elif cmd == "REGISTER_DOCTOR":
        doc = data.get("doctor", "")
        spec = data.get("specialization", "General")
        ins = data.get("accepted_insurance", [])
        port = data.get("udp_port", 5000)
        slots = data.get("slots", ["9AM", "11AM", "2PM", "4PM"])
        return scheduler.register_doctor(doc, spec, ins, port, slots)

    return {"status": "ERROR", "reason": "Unknown command"}


async def main() -> None:
    global _is_shutting_down
    loop = asyncio.get_running_loop()

    # Try loading TLS context, fallback to plain TCP if cert generation unneeded/optional
    ssl_context = None
    try:
        ssl_context = get_server_ssl_context()
        log("TLS SSLContext initialized for server", level="INFO")
    except Exception as e:
        log(f"TLS context initialization skipped: {e}. Running in standard TCP mode.", level="WARN")

    server = await asyncio.start_server(handle_client, HOST, PORT, ssl=ssl_context)
    addr = server.sockets[0].getsockname()
    log(f"Health Server running on {addr[0]}:{addr[1]} (Asyncio Core)", level="INFO")

    stop_event = asyncio.Event()

    def _on_shutdown_signal():
        global _is_shutting_down
        log("Shutdown signal received! Initiating graceful shutdown...", level="WARN")
        _is_shutting_down = True
        stop_event.set()

    # Trapping SIGINT and SIGTERM
    if sys.platform != "win32":
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, _on_shutdown_signal)

    try:
        await stop_event.wait()
    except (KeyboardInterrupt, asyncio.CancelledError):
        _is_shutting_down = True

    log("Notifying connected clients of shutdown...", level="INFO")
    await _broadcast_to_subs({"status": "SHUTDOWN", "reason": "Server undergoing graceful shutdown"})

    server.close()
    await server.wait_closed()
    log("Server shutdown completed cleanly.", level="INFO")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nServer terminated by user.")
