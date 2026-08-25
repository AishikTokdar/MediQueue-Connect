import json
import os
import sys
import threading
from datetime import datetime
from typing import Optional
from db import add_audit_log

LOG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "server_logs.txt")
_lock = threading.Lock()


def log(message: str, level: str = "INFO", trace_id: Optional[str] = None, client_ip: Optional[str] = None) -> None:
    timestamp = datetime.now().isoformat()
    log_record = {
        "timestamp": timestamp,
        "level": level,
        "trace_id": trace_id,
        "client_ip": client_ip,
        "message": message,
    }
    
    formatted_entry = f"[{timestamp}] [{level}]"
    if trace_id:
        formatted_entry += f" [trace:{trace_id}]"
    if client_ip:
        formatted_entry += f" [ip:{client_ip}]"
    formatted_entry += f" {message}"

    try:
        print(formatted_entry)
    except UnicodeEncodeError:
        encoding = getattr(sys.stdout, "encoding", "utf-8") or "utf-8"
        print(formatted_entry.encode(encoding, errors="replace").decode(encoding))

    with _lock:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(log_record) + "\n")


def log_audit(action: str, user: Optional[str] = None, trace_id: Optional[str] = None, details: Optional[str] = None) -> None:
    log(f"AUDIT ACTION: {action} | User: {user} | Details: {details}", level="AUDIT", trace_id=trace_id)
    try:
        add_audit_log(action=action, user=user, trace_id=trace_id, details=details)
    except Exception as e:
        log(f"Failed to record DB audit log: {e}", level="ERROR", trace_id=trace_id)
