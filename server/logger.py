import os
import sys
import threading
from datetime import datetime

LOG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "server_logs.txt")
_lock = threading.Lock()


def log(message: str) -> None:
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    entry = f"[{timestamp}] {message}"
    try:
        print(entry)
    except UnicodeEncodeError:
        encoding = getattr(sys.stdout, "encoding", "utf-8") or "utf-8"
        print(entry.encode(encoding, errors="replace").decode(encoding))
    with _lock:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(entry + "\n")
