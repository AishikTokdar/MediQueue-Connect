import socket
import json
import time
import os
import sys
import argparse
from datetime import datetime
from crypto_utils import wrap_client_socket

HOST = "127.0.0.1"
PORT = 4000
LOG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "server_logs.txt")

RESET   = "\033[0m"
BOLD    = "\033[1m"
RED     = "\033[91m"
GREEN   = "\033[92m"
YELLOW  = "\033[93m"
CYAN    = "\033[96m"
MAGENTA = "\033[95m"
DIM     = "\033[2m"
CLEAR   = "\033[2J\033[H"


def ansi(code: str, text: str) -> str:
    return f"{code}{text}{RESET}"


def color_status(online: bool, busy: bool) -> str:
    if not online:
        return ansi(DIM, "○ OFFLINE")
    if busy:
        return ansi(RED + BOLD, "● BUSY")
    return ansi(GREEN + BOLD, "● FREE")


from protocol import send_framed, recv_framed


def fetch_dashboard() -> dict | None:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(3.0)
        s.connect((HOST, PORT))
        s = wrap_client_socket(s, server_hostname=HOST)
        send_framed(s, {"command": "GET_STATS"})
        resp = recv_framed(s)
        s.close()
        return resp
    except Exception:
        return None


def tail_log(n: int = 8) -> list[str]:
    try:
        with open(LOG_FILE, encoding="utf-8") as f:
            lines = f.readlines()
        return [l.rstrip() for l in lines[-n:]]
    except FileNotFoundError:
        return []


def render(data: dict, interval: float) -> None:
    queue_state: dict = data.get("queue_state", {})
    stats: dict = data.get("stats", {})
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    out = []
    W = 60

    out.append(CLEAR)
    out.append(ansi(CYAN + BOLD, "╔" + "═" * (W - 2) + "╗"))
    out.append(ansi(CYAN + BOLD, f"║{'  🏥  HEALTHCARE SYSTEM DASHBOARD':^{W-2}}║"))
    out.append(ansi(CYAN + BOLD, f"║{f'  Updated: {now}  (every {interval}s)':^{W-2}}║"))
    out.append(ansi(CYAN + BOLD, "╚" + "═" * (W - 2) + "╝"))

    out.append("")
    out.append(ansi(BOLD, "  DOCTOR STATUS"))
    out.append("  " + "─" * (W - 4))

    if not queue_state:
        out.append("  (no data yet)")
    else:
        for doctor, info in sorted(queue_state.items()):
            busy = info.get("busy", False)
            online = info.get("online", False)
            active = info.get("active_patient") or "—"
            queue = info.get("queue", [])

            out.append(f"  {ansi(BOLD, doctor):30}  {color_status(online, busy)}")

            if busy:
                out.append(f"    {ansi(DIM, 'Active patient:')}  {ansi(YELLOW, active)}")
            if queue:
                q_str = ", ".join(queue)
                out.append(f"    {ansi(DIM, 'Queue')}: [{ansi(MAGENTA, q_str)}]  ({len(queue)} waiting)")
            out.append("")

    uptime = stats.get("uptime", 0)
    m, s = divmod(uptime, 60)
    h, m = divmod(m, 60)
    uptime_str = f"{h:02d}:{m:02d}:{s:02d}"

    out.append("  " + "─" * (W - 4))
    out.append(ansi(BOLD, "  SYSTEM COUNTERS"))
    out.append("  " + "─" * (W - 4))
    out.append(f"    Server Uptime : {ansi(CYAN, uptime_str)}")
    out.append(f"    Total Logins  : {ansi(CYAN, str(stats.get('total_logins', 0)))}")
    out.append(f"    Total Bookings: {ansi(CYAN, str(stats.get('total_bookings', 0)))}")
    out.append(f"    Total Chats   : {ansi(CYAN, str(stats.get('total_chats', 0)))}")

    out.append("")
    out.append("  " + "─" * (W - 4))
    out.append(ansi(BOLD, "  RECENT LOG  (last 8 entries)"))
    out.append("  " + "─" * (W - 4))
    for line in tail_log(8):
        out.append(f"  {ansi(DIM, line)}")

    out.append("")
    banned_ips = data.get("banned_ips", [])
    if banned_ips:
        out.append("  " + "─" * (W - 4))
        out.append(ansi(RED + BOLD, "  BANNED IPs (DDoS Protection)"))
        out.append("  " + "─" * (W - 4))
        for ip in banned_ips:
            out.append(f"    {ansi(RED, ip)}")
        out.append("")

    out.append(ansi(DIM, "  Press Ctrl+C to exit."))

    print("\n".join(out), flush=True)


def render_error(interval: float) -> None:
    now = datetime.now().strftime("%H:%M:%S")
    print(
        CLEAR +
        ansi(RED + BOLD, f"\n  ⚠  Cannot reach Health Server ({HOST}:{PORT})\n") +
        f"  [{now}]  Retrying in {interval}s...\n" +
        ansi(DIM, "  Press Ctrl+C to exit."),
        flush=True
    )


def main():
    p = argparse.ArgumentParser(description="Healthcare system monitoring dashboard")
    p.add_argument("--interval", type=float, default=4.0, help="Polling interval in seconds")
    args = p.parse_args()

    if sys.platform == "win32":
        os.system("")  # enable VT100/ANSI on Windows

    print(ansi(CYAN, "Starting dashboard... (Ctrl+C to exit)"), flush=True)

    try:
        while True:
            data = fetch_dashboard()
            if data:
                render(data, args.interval)
            else:
                print("\nHealth Server stopped", flush=True)
                sys.exit(1)
            time.sleep(args.interval)
    except KeyboardInterrupt:
        print("\n\nDashboard closed.")


if __name__ == "__main__":
    main()
