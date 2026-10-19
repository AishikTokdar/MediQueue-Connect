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
from db import (
    get_audit_logs,
    export_audit_logs_to_csv,
    init_db,
    save_prescription,
    get_prescriptions_for_patient,
    get_prescription_by_session,
    save_patient_profile,
    get_patient_profile,
    save_doctor_review,
    get_doctor_rating_stats,
    get_doctor_reviews_list,
)
from logger import log, log_audit
from protocol import async_recv_framed, async_send_framed
from queue_manager import QueueManager
from scheduler import Scheduler
from schemas import validate_request_payload
from metrics import (
    ACTIVE_CONNECTIONS,
    BOOKINGS_TOTAL,
    QUEUE_DEPTH,
    REQUEST_LATENCY,
    REQUESTS_TOTAL,
    CELERY_TASKS_TOTAL,
    start_metrics_server,
)
from tasks import (
    generate_session_summary_pdf_task,
    generate_pdf_summary_internal,
    send_email_reminder_task,
    send_sms_reminder_task,
)



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

_SERVER_NODE_ID = str(uuid.uuid4())[:8]
_active_subs_lock = asyncio.Lock()
_active_subs: List[asyncio.StreamWriter] = []
_is_shutting_down = False
_running_loop: Optional[asyncio.AbstractEventLoop] = None


async def _incr_stat(key: str) -> None:
    async with _stats_lock:
        _stats[key] += 1


async def _dispatch_local_broadcast(payload: Dict[str, Any]) -> None:
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


async def _broadcast_to_subs(payload: Dict[str, Any]) -> None:
    enriched = dict(payload)
    enriched["_origin_node"] = _SERVER_NODE_ID
    await _dispatch_local_broadcast(enriched)
    try:
        scheduler.cache.publish_event("mediqueue:broadcasts", enriched)
    except Exception as e:
        log(f"Redis event bus publish notice: {e}", level="WARN")


def _handle_remote_event_bus(event: Dict[str, Any]) -> None:
    if event.get("_origin_node") == _SERVER_NODE_ID:
        return
    if _running_loop and _running_loop.is_running() and not _is_shutting_down:
        _running_loop.call_soon_threadsafe(asyncio.create_task, _dispatch_local_broadcast(event))


async def handle_client(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    peer_info = writer.get_extra_info("peername")
    client_ip = peer_info[0] if peer_info else "unknown"

    ACTIVE_CONNECTIONS.inc()
    try:
        while not _is_shutting_down:
            if not await rate_limiter.allow(client_ip):
                log(f"IP {client_ip} rate limited & banned", level="WARN", client_ip=client_ip)
                REQUESTS_TOTAL.labels(command="UNKNOWN", status="BANNED").inc()
                await async_send_framed(writer, {"status": "ERROR", "reason": "Rate limit exceeded. Temporary IP ban."})
                break

            data = await async_recv_framed(reader)
            if data is None:
                break

            trace_id = str(uuid.uuid4())[:8]
            cmd = data.get("command", "UNKNOWN")
            log(f"Received command: {cmd}", level="INFO", trace_id=trace_id, client_ip=client_ip)

            is_valid, err_msg, validated_payload = validate_request_payload(cmd, data)
            if not is_valid:
                log(f"Invalid payload for {cmd}: {err_msg}", level="WARN", trace_id=trace_id)
                REQUESTS_TOTAL.labels(command=cmd, status="INVALID_SCHEMA").inc()
                await async_send_framed(writer, {"status": "ERROR", "reason": err_msg})
                continue

            t0 = time.perf_counter()
            resp = await process_command(cmd, data, client_ip, trace_id, writer)
            t1 = time.perf_counter()
            
            status = resp.get("status", "OK") if resp else "NO_RESPONSE"
            REQUESTS_TOTAL.labels(command=cmd, status=status).inc()
            REQUEST_LATENCY.labels(command=cmd).observe(t1 - t0)

            if resp is not None:
                await async_send_framed(writer, resp)

    finally:
        ACTIVE_CONNECTIONS.dec()
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
            insurance = auth.get_insurance(token)
            return {"status": "OK", "token": token, "username": username, "insurance": insurance}
        else:
            log("Login failed", level="WARN", trace_id=trace_id, client_ip=client_ip)
            return {"status": "FAIL", "reason": "Invalid credentials"}

    elif cmd == "DOCTOR_LOGIN":
        doctor = data.get("doctor", "")
        password = data.get("password", "")
        if auth.authenticate_doctor(doctor, password):
            token = str(uuid.uuid4())
            auth.create_session(token, doctor, role="doctor")
            await _incr_stat("total_logins")
            log_audit("DOCTOR_LOGIN", user=doctor, trace_id=trace_id, details=f"IP: {client_ip}")
            return {"status": "OK", "token": token, "doctor": doctor, "role": "doctor"}
        else:
            log(f"Doctor login failed for {doctor}", level="WARN", trace_id=trace_id, client_ip=client_ip)
            return {"status": "FAIL", "reason": "Invalid doctor credentials"}

    elif cmd == "REGISTER":
        username = data.get("username", "")
        password = data.get("password", "")
        insurance = data.get("insurance", [])
        if auth.register(username, password, insurance):
            token = str(uuid.uuid4())
            auth.create_session(token, username)
            await _incr_stat("total_logins")
            log_audit("USER_REGISTER", user=username, trace_id=trace_id)
            return {"status": "OK", "token": token, "username": username, "insurance": insurance}
        else:
            return {"status": "FAIL", "reason": "Username already exists"}

    elif cmd == "UPDATE_PROFILE":
        token = data.get("token", "")
        if not auth.validate(token):
            return {"status": "ERROR", "reason": "Invalid token"}
        user = auth.get_user(token)
        dob = data.get("dob", "")
        blood_group = data.get("blood_group", "")
        allergies = data.get("allergies", [])
        conditions = data.get("chronic_conditions", [])
        contact = data.get("emergency_contact", "")
        save_patient_profile(user, dob=dob, blood_group=blood_group, allergies=allergies, chronic_conditions=conditions, emergency_contact=contact)
        log_audit("UPDATE_PATIENT_PROFILE", user=user, trace_id=trace_id)
        return {"status": "OK"}

    elif cmd == "GET_PROFILE":
        token = data.get("token", "")
        if not auth.validate(token):
            return {"status": "ERROR", "reason": "Invalid token"}
        user = auth.get_user(token)
        prof = get_patient_profile(user)
        return {"status": "OK", "profile": prof or {}}

    elif cmd == "GET_SLOTS":
        token = data.get("token", "")
        if not auth.validate(token):
            return {"status": "ERROR", "reason": "Invalid token"}
        user_insurance = auth.get_insurance(token)
        specialization = data.get("specialization")
        appointment_date = data.get("appointment_date")
        slots = scheduler.get_slots(user_insurance, specialization, appointment_date=appointment_date)
        return {"status": "OK", "doctors": slots, "appointment_date": appointment_date}

    elif cmd in ("BOOK", "BOOK_SLOT"):
        token = data.get("token", "")
        if not auth.validate(token):
            return {"status": "ERROR", "reason": "Invalid token"}
        user = auth.get_user(token)
        doctor = data.get("doctor", "")
        slot = data.get("slot", "")
        appointment_date = data.get("appointment_date")
        resp = scheduler.book_slot(user, doctor, slot, appointment_date=appointment_date)
        if resp.get("status") == "BOOKED":
            await _incr_stat("total_bookings")
            BOOKINGS_TOTAL.inc()
            log_audit("BOOK_APPOINTMENT", user=user, trace_id=trace_id, details=f"Doctor: {doctor}, Slot: {slot}, Date: {resp.get('appointment_date')}")
            try:
                send_email_reminder_task.delay(f"{user}@mediqueue.org", user, doctor, slot)
                send_sms_reminder_task.delay("+15550192834", user, doctor, slot)
                CELERY_TASKS_TOTAL.labels(task_name="send_email_reminder_task", status="ENQUEUED").inc()
                CELERY_TASKS_TOTAL.labels(task_name="send_sms_reminder_task", status="ENQUEUED").inc()
            except Exception as e:
                log(f"Celery task dispatch notice: {e}", level="INFO")
        return resp


    elif cmd in ("MY_BOOKINGS", "GET_MY_APPOINTMENTS"):
        token = data.get("token", "")
        if not auth.validate(token):
            return {"status": "ERROR", "reason": "Invalid token"}
        user = auth.get_user(token)
        bookings = scheduler.get_bookings_for_patient(user)
        return {"status": "OK", "bookings": bookings, "appointments": bookings}

    elif cmd in ("CANCEL_BOOKING", "CANCEL_MY_BOOKING"):
        token = data.get("token", "")
        if not auth.validate(token):
            return {"status": "ERROR", "reason": "Invalid token"}
        user = auth.get_user(token)
        doctor = data.get("doctor", "")
        slot = data.get("slot", "")
        appointment_date = data.get("appointment_date")
        return scheduler.remove_booking_for_patient(user, doctor, slot, appointment_date=appointment_date)

    elif cmd == "GET_DOCTORS":
        token = data.get("token", "")
        if not auth.validate(token):
            return {"status": "ERROR", "reason": "Invalid token"}
        user_insurance = auth.get_insurance(token)
        specialization = data.get("specialization")
        all_docs = scheduler.get_all_doctors()
        filtered = {}
        for d_name, d_info in all_docs.items():
            acc_ins = d_info.get("accepted_insurance", [])
            spec = d_info.get("specialization", "")
            if user_insurance and not any(i in acc_ins for i in user_insurance):
                continue
            if specialization and specialization.lower() not in spec.lower():
                continue
            filtered[d_name] = {
                "online": queue_mgr.is_online(d_name),
                "specialization": spec,
                "accepted_insurance": acc_ins,
                "udp_port": d_info.get("udp_port", 5000),
            }
        return {"status": "OK", "doctors": filtered}

    elif cmd == "REQUEST_CHAT":
        token = data.get("token", "")
        if not auth.validate(token):
            return {"status": "ERROR", "reason": "Invalid token"}
        user = auth.get_user(token)
        doctor = data.get("doctor", "")
        all_docs = scheduler.get_all_doctors()
        doc_info = all_docs.get(doctor, {})
        udp_port = doc_info.get("udp_port", 5000)

        if not queue_mgr.is_busy(doctor):
            if queue_mgr.try_start_session(doctor, user):
                log_audit("START_CONSULTATION", user=user, trace_id=trace_id, details=f"Doctor: {doctor}")
                return {"status": "READY", "udp_port": udp_port}

        esi_level = int(data.get("esi_level") or 5)
        pos = queue_mgr.enqueue(doctor, user, esi_level=esi_level)
        QUEUE_DEPTH.labels(doctor=doctor).set(len(queue_mgr.get_queue(doctor)))
        log_audit("JOIN_QUEUE", user=user, trace_id=trace_id, details=f"Doctor: {doctor}, Pos: {pos}, ESI: {esi_level}")
        return {"status": "QUEUED", "position": pos, "doctor": doctor, "udp_port": udp_port, "esi_level": esi_level}

    elif cmd == "JOIN_QUEUE":
        token = data.get("token", "")
        if not auth.validate(token):
            return {"status": "ERROR", "reason": "Invalid token"}
        user = auth.get_user(token)
        doctor = data.get("doctor", "")
        esi_level = int(data.get("esi_level") or 5)
        pos = queue_mgr.enqueue(doctor, user, esi_level=esi_level)
        QUEUE_DEPTH.labels(doctor=doctor).set(len(queue_mgr.get_queue(doctor)))
        log_audit("JOIN_QUEUE", user=user, trace_id=trace_id, details=f"Doctor: {doctor}, Pos: {pos}, ESI: {esi_level}")
        return {"status": "QUEUED", "position": pos, "doctor": doctor, "esi_level": esi_level}

    elif cmd in ("LEAVE_QUEUE", "CANCEL_QUEUE"):
        token = data.get("token", "")
        if not auth.validate(token):
            return {"status": "ERROR", "reason": "Invalid token"}
        user = auth.get_user(token)
        doctor = data.get("doctor", "")
        success = queue_mgr.dequeue_patient(doctor, user)
        QUEUE_DEPTH.labels(doctor=doctor).set(len(queue_mgr.get_queue(doctor)))
        return {"status": "OK" if success else "FAIL"}

    elif cmd == "START_CHAT":
        token = data.get("token", "")
        if not auth.validate(token):
            return {"status": "ERROR", "reason": "Invalid token"}
        user = auth.get_user(token)
        doctor = data.get("doctor", "")
        session_id = data.get("session_id", str(uuid.uuid4()))
        chat_hist.start_session(session_id, doctor, user)
        return {"status": "OK"}

    elif cmd == "END_SESSION":
        doctor = data.get("doctor", "")
        session_id = data.get("session_id", "")
        patient = data.get("patient", "")
        transcript = data.get("transcript", [])
        if session_id:
            if transcript:
                chat_hist.sync_transcript(session_id, doctor, patient or "patient", transcript)
            else:
                chat_hist.end_session(session_id)
        next_patient = queue_mgr.end_session(doctor)
        return {"status": "OK", "next_patient": next_patient[0] if isinstance(next_patient, tuple) else next_patient}

    elif cmd == "SYNC_TRANSCRIPT":
        doctor = data.get("doctor", "")
        session_id = data.get("session_id", "")
        patient = data.get("patient", "")
        transcript = data.get("transcript", [])
        if session_id and transcript:
            path = chat_hist.sync_transcript(session_id, doctor, patient or "patient", transcript)
            return {"status": "OK", "path": path}
        return {"status": "FAIL", "reason": "Missing session_id or transcript payload"}

    elif cmd == "ISSUE_PRESCRIPTION":
        token = data.get("token")
        if token != "DOCTOR_INTERNAL" and not (token and auth.validate(token) and auth.get_role(token) == "doctor"):
            return {"status": "ERROR", "reason": "Unauthorized: Doctor credentials required"}
        session_id = data.get("session_id", "")
        doctor = data.get("doctor", "")
        patient = data.get("patient", "")
        diagnosis = data.get("diagnosis", "")
        meds = data.get("medications", [])
        instructions = data.get("instructions", "")
        rx_id = save_prescription(session_id, doctor, patient, diagnosis, meds, instructions)
        log_audit("ISSUE_PRESCRIPTION", user=doctor, trace_id=trace_id, details=f"Rx ID: {rx_id}, Patient: {patient}, Diagnosis: {diagnosis}")
        return {"status": "OK", "prescription_id": rx_id}

    elif cmd == "GET_MY_PRESCRIPTIONS":
        token = data.get("token", "")
        if not auth.validate(token):
            return {"status": "ERROR", "reason": "Invalid token"}
        user = auth.get_user(token)
        rx_list = get_prescriptions_for_patient(user)
        return {"status": "OK", "prescriptions": rx_list}

    elif cmd == "SUBMIT_REVIEW":
        token = data.get("token", "")
        if not auth.validate(token):
            return {"status": "ERROR", "reason": "Invalid token"}
        user = auth.get_user(token)
        doctor = data.get("doctor", "")
        rating = data.get("rating", 5)
        review = data.get("review", "")
        session_id = data.get("session_id", "")
        review_id = save_doctor_review(doctor, user, rating, review=review, session_id=session_id)
        scheduler.cache.invalidate_slots_cache()
        log_audit("SUBMIT_REVIEW", user=user, trace_id=trace_id, details=f"Doctor: {doctor}, Rating: {rating}")
        stats = get_doctor_rating_stats(doctor)
        return {"status": "OK", "review_id": review_id, "stats": stats}

    elif cmd == "GET_DOCTOR_REVIEWS":
        doctor = data.get("doctor", "")
        reviews = get_doctor_reviews_list(doctor)
        stats = get_doctor_rating_stats(doctor)
        return {"status": "OK", "doctor": doctor, "stats": stats, "reviews": reviews}

    elif cmd == "GENERATE_TRANSCRIPT_PDF":
        token = data.get("token")
        session_id = data.get("session_id", "")
        doctor = data.get("doctor", "")
        patient = data.get("patient", "")
        if not patient and token and auth.validate(token):
            patient = auth.get_user(token)
        if not patient:
            patient = "patient"

        try:
            task = generate_session_summary_pdf_task.delay(session_id, doctor, patient)
            CELERY_TASKS_TOTAL.labels(task_name="generate_session_summary_pdf_task", status="ENQUEUED").inc()
            
            result_info = None
            if task.ready():
                result_info = task.result

            default_path = os.path.abspath(
                os.path.join(os.path.dirname(__file__), "..", "data", "summaries", doctor, f"{session_id}_summary.pdf")
            )
            pdf_path = (result_info.get("pdf_path") if isinstance(result_info, dict) else None) or default_path

            return {
                "status": "OK",
                "task_id": str(task.id),
                "pdf_path": pdf_path,
                "message": f"PDF summary task queued successfully (Task ID: {task.id})",
            }
        except Exception as e:
            log(f"Celery dispatch failed, executing synchronous fallback PDF generation: {e}", level="WARN")
            res = generate_pdf_summary_internal(session_id, doctor, patient)
            return {
                "status": "OK",
                "pdf_path": res.get("pdf_path"),
                "message": "PDF summary generated directly.",
            }


    elif cmd == "GET_TASK_STATUS":
        task_id = data.get("task_id", "")
        try:
            from celery.result import AsyncResult
            res = AsyncResult(task_id)
            return {
                "status": "OK",
                "task_id": task_id,
                "state": res.state,
                "result": res.result if res.ready() else None,
            }
        except Exception as e:
            return {"status": "ERROR", "reason": str(e)}


    elif cmd == "DOCTOR_ONLINE":
        doctor = data.get("doctor", "")
        queue_mgr.set_online(doctor, True)
        log(f"Doctor {doctor} is now ONLINE", level="INFO", trace_id=trace_id)
        return {"status": "OK"}

    elif cmd == "DOCTOR_OFFLINE":
        doctor = data.get("doctor", "")
        queue_mgr.set_online(doctor, False)
        log(f"Doctor {doctor} is now OFFLINE", level="INFO", trace_id=trace_id)
        return {"status": "OK"}

    elif cmd == "NEXT_PATIENT":
        token = data.get("token", "")
        if not auth.validate(token):
            return {"status": "ERROR", "reason": "Invalid token"}
        doctor = data.get("doctor", "")
        next_item = queue_mgr.end_session(doctor)
        QUEUE_DEPTH.labels(doctor=doctor).set(len(queue_mgr.get_queue(doctor)))
        if next_item:
            next_patient = next_item[0]
            esi_level = next_item[2] if len(next_item) > 2 else 5
            await _incr_stat("total_chats")
            log_audit("NEXT_PATIENT", user=doctor, trace_id=trace_id, details=f"Patient: {next_patient}, ESI: {esi_level}")
            prof = get_patient_profile(next_patient)
            return {"status": "OK", "next_patient": next_patient, "esi_level": esi_level, "profile": prof or {}}
        return {"status": "EMPTY", "reason": "No patients in queue"}

    elif cmd == "GET_PATIENT_INTAKE":
        token = data.get("token")
        if token != "DOCTOR_INTERNAL" and not (token and auth.validate(token) and auth.get_role(token) == "doctor"):
            return {"status": "ERROR", "reason": "Unauthorized: Doctor credentials required"}
        patient = data.get("patient", "")
        prof = get_patient_profile(patient)
        return {"status": "OK", "profile": prof or {}}

    elif cmd == "GET_QUEUE":
        token = data.get("token", "")
        if not auth.validate(token):
            return {"status": "ERROR", "reason": "Invalid token"}
        doctor = data.get("doctor", "")
        q = queue_mgr.get_queue(doctor)
        details = queue_mgr.get_queue_details(doctor)
        return {"status": "OK", "queue": q, "queue_details": details}

    elif cmd == "GET_SPECIALIZATIONS":
        specs = scheduler.get_specializations()
        return {"status": "OK", "specializations": specs}

    elif cmd == "GET_STATS":
        banned = await rate_limiter.get_banned_ips()
        async with _stats_lock:
            st = dict(_stats)
        uptime = int(time.time() - _start_time)
        st["uptime"] = uptime
        st["uptime_seconds"] = uptime
        st["banned_ips"] = banned
        st["all_bookings"] = scheduler.get_all_bookings()
        st["all_queues"] = queue_mgr.get_all_queues()
        st["queue_state"] = queue_mgr.snapshot()
        st["doctors"] = scheduler.get_all_doctors()
        return {"status": "OK", "stats": st, "queue_state": st["queue_state"], "banned_ips": banned}

    elif cmd in ("SUBSCRIBE", "SUBSCRIBE_STATS"):
        async with _active_subs_lock:
            if writer not in _active_subs:
                _active_subs.append(writer)
        return {"status": "SUBSCRIBED"}

    elif cmd == "ADMIN_GET_BOOKINGS":
        return {"status": "OK", "bookings": scheduler.get_all_bookings()}

    elif cmd in ("CLEAR_BOOKING", "ADMIN_REMOVE_BOOKING"):
        doctor = data.get("doctor", "")
        slot = data.get("slot", "")
        appointment_date = data.get("appointment_date")
        success = scheduler.remove_booking(doctor, slot, appointment_date=appointment_date)
        return {"status": "OK" if success else "FAIL"}

    elif cmd == "ADMIN_KILL_SESSION":
        session_id = data.get("session_id", "")
        await _broadcast_to_subs({"status": "KILL_SESSION", "session_id": session_id})
        return {"status": "OK"}

    elif cmd == "ADMIN_BANNED_IPS":
        banned = await rate_limiter.get_banned_ips()
        return {"status": "OK", "banned_ips": banned}

    elif cmd in ("UNBAN_IP", "ADMIN_UNBAN_IP"):
        ip = data.get("ip", "")
        unbanned = await rate_limiter.unban(ip)
        log_audit("UNBAN_IP", user="ADMIN", trace_id=trace_id, details=f"IP: {ip}")
        return {"status": "OK" if unbanned else "FAIL"}

    elif cmd == "ADMIN_GLOBAL_MSG":
        msg = data.get("message", "")
        await _broadcast_to_subs({"status": "GLOBAL_MSG", "message": msg})
        return {"status": "OK"}

    elif cmd in ("AUDIT_LOGS", "ADMIN_GET_AUDIT_LOGS"):
        limit = data.get("limit", 50)
        user = data.get("user")
        action = data.get("action")
        keyword = data.get("keyword")
        logs = get_audit_logs(limit=limit, user=user, action=action, keyword=keyword)
        return {"status": "OK", "logs": logs, "count": len(logs)}

    elif cmd == "ADMIN_EXPORT_AUDIT_CSV":
        user = data.get("user")
        action = data.get("action")
        keyword = data.get("keyword")
        limit = data.get("limit", 1000)
        csv_path = export_audit_logs_to_csv(user=user, action=action, keyword=keyword, limit=limit)
        return {"status": "OK", "csv_path": csv_path}

    elif cmd == "REGISTER_DOCTOR":
        doc = data.get("doctor", "")
        spec = data.get("specialization", "General")
        ins = data.get("accepted_insurance", [])
        port = data.get("udp_port", 5000)
        slots = data.get("slots", ["9AM", "11AM", "2PM", "4PM"])
        return scheduler.register_doctor(doc, spec, ins, port, slots)

    return {"status": "ERROR", "reason": "Unknown command"}


async def main() -> None:
    global _is_shutting_down, _running_loop
    loop = asyncio.get_running_loop()
    _running_loop = loop

    try:
        scheduler.cache.subscribe_events("mediqueue:broadcasts", _handle_remote_event_bus)
        log("Distributed Redis Pub/Sub broadcast event bus initialized", level="INFO")
    except Exception as e:
        log(f"Redis Pub/Sub subscription notice: {e}", level="WARN")

    if start_metrics_server(8000):
        log("Prometheus operational telemetry exporter started on http://127.0.0.1:8000/metrics", level="INFO")

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
