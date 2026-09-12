import json
import os
import sys
import socket
from pathlib import Path
from crypto_utils import wrap_client_socket

_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = _ROOT / "data"
CHAT_HISTORY_DIR = DATA_DIR / "chat_history"

HOST = "127.0.0.1"
PORT = 4000

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

from protocol import send_framed, recv_framed


def tcp_send(payload: dict) -> dict | None:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(3.0)
        s.connect((HOST, PORT))
        s = wrap_client_socket(s, server_hostname=HOST)
        send_framed(s, payload)
        resp = recv_framed(s)
        s.close()
        return resp
    except Exception as e:
        print(ansi(RED, f"\nError communicating with Health Server: {e}"))
        return None

def display_bookings(bookings: dict) -> None:
    active_bookings = {doctor: slots for doctor, slots in bookings.items() if slots}
    if not active_bookings:
        print(ansi(YELLOW, "\n  No bookings found."))
        return
    print("\n" + ansi(CYAN + BOLD, "═" * 55))
    print(ansi(CYAN + BOLD, "  CURRENT BOOKINGS"))
    print(ansi(CYAN + BOLD, "═" * 55))
    for doctor, slots in active_bookings.items():
        print(f"  {ansi(BOLD, 'Doctor:')} {ansi(GREEN, doctor)}")
        for slot, patient in slots.items():
            print(f"    {ansi(YELLOW, slot):10}  →  {patient}")
    print(ansi(CYAN + BOLD, "═" * 55))

def remove_booking(bookings: dict) -> bool:
    active_bookings = {doctor: slots for doctor, slots in bookings.items() if slots}
    if not active_bookings:
        print(ansi(YELLOW, "\n  No bookings found."))
        return False

    print("\n" + ansi(CYAN + BOLD, "═" * 55))
    print(ansi(CYAN + BOLD, "  DOCTORS WITH BOOKINGS"))
    print(ansi(CYAN + BOLD, "═" * 55))
    for doctor in active_bookings:
        print(f"  - {ansi(GREEN, doctor)}")
    print(ansi(CYAN + BOLD, "═" * 55))

    doctor = input("\nEnter doctor name: ").strip()
    slot = input("Enter slot: ").strip()

    if not doctor or not slot:
        print(ansi(RED, "Error: Doctor name and slot cannot be empty"))
        return False

    # Allow case-insensitive doctor name input while preserving canonical key.
    doctor_lookup = {name.lower(): name for name in active_bookings}
    doctor_key = doctor_lookup.get(doctor.lower())
    if not doctor_key:
        print(ansi(RED, f"Error: Doctor '{doctor}' not found in bookings"))
        return False

    if slot not in active_bookings[doctor_key]:
        print(ansi(RED, f"Error: Slot '{slot}' not found for doctor '{doctor_key}'"))
        return False

    patient = active_bookings[doctor_key][slot]
    print(ansi(MAGENTA, f"\nConfirm deletion – Patient: {ansi(BOLD, patient)}, Slot: {ansi(BOLD, slot)}"))
    confirm = input("Are you sure? (y/n): ").strip().lower()
    if confirm != "y":
        print(ansi(DIM, "Deletion cancelled"))
        return False

    res = tcp_send({"command": "ADMIN_REMOVE_BOOKING", "doctor": doctor_key, "slot": slot})
    if res and res.get("status") == "OK":
        print(ansi(GREEN + BOLD, "[OK] Booking removed successfully via Server"))

        return True
    else:
        print(ansi(RED, f"Failed to remove booking: {res.get('reason', 'Unknown error')}"))
        return False

def list_chat_sessions() -> None:
    if not CHAT_HISTORY_DIR.exists():
        print(ansi(YELLOW, "\nNo chat history found."))
        return

    sessions = []
    for doctor_dir in sorted(CHAT_HISTORY_DIR.iterdir()):
        if doctor_dir.is_dir():
            for session_file in sorted(doctor_dir.glob("*.jsonl")):
                sessions.append((doctor_dir.name, session_file))

    if not sessions:
        print(ansi(YELLOW, "\nNo chat history found."))
        return

    print("\n" + ansi(MAGENTA + BOLD, "═" * 55))
    print(ansi(MAGENTA + BOLD, "  CHAT SESSIONS"))
    print(ansi(MAGENTA + BOLD, "═" * 55))
    for idx, (doctor, path) in enumerate(sessions, 1):
        patient = "?"
        msg_count = 0
        with open(path, encoding="utf-8") as f:
            for line in f:
                try:
                    rec = json.loads(line)
                    if rec.get("event") == "SESSION_START":
                        patient = rec.get("patient", "?")
                    if "sender" in rec:
                        msg_count += 1
                except json.JSONDecodeError:
                    pass
        print(f"  [{ansi(CYAN, str(idx)):2}] {ansi(GREEN, doctor):12} ↔ {ansi(YELLOW, patient):12}  msgs={ansi(DIM, str(msg_count)):3}  {path.name}")
    print(ansi(MAGENTA + BOLD, "═" * 55))

    choice = input("Enter session number to view, 'kill <num>' to terminate, or Enter to skip: ").strip()
    if choice.startswith("kill "):
        idx_str = choice.split()[1]
        if idx_str.isdigit():
            idx = int(idx_str) - 1
            if 0 <= idx < len(sessions):
                session_id = sessions[idx][1].stem
                res = tcp_send({"command": "ADMIN_KILL_SESSION", "session_id": session_id})
                if res and res.get("status") == "OK":
                    print(ansi(GREEN, f"[OK] Triggered KILL_SESSION for {session_id}"))
                else:
                    print(ansi(RED, "[FAILED] Failed to kill session."))

    elif choice.isdigit():
        idx = int(choice) - 1
        if 0 <= idx < len(sessions):
            view_session(sessions[idx][1])

def view_session(path: Path) -> None:
    print(ansi(CYAN + BOLD, f"\n── Session: {path.name} " + "─" * (52 - len(path.name))))
    with open(path, encoding="utf-8") as f:
        for line in f:
            try:
                rec = json.loads(line)
                ts = rec.get("ts", "")
                if "event" in rec:
                    print(ansi(DIM, f"  [{ts}] *** {rec['event']} ***"))
                elif "sender" in rec:
                    print(f"  [{ansi(DIM, ts)}] {ansi(GREEN, rec['sender']):12}: {rec.get('text', '')}")
            except json.JSONDecodeError:
                pass
    print(ansi(CYAN + BOLD, "─" * 55))

def manage_security() -> None:
    res = tcp_send({"command": "ADMIN_BANNED_IPS"})
    if not res or res.get("status") != "OK":
        print(ansi(RED, "[FAILED] Failed to fetch banned IPs."))
        return
        
    banned_ips = res.get("banned_ips", [])
    if not banned_ips:
        print(ansi(GREEN, "\n  No IPs are currently banned."))
        return
        
    print("\n" + ansi(RED + BOLD, "═" * 55))
    print(ansi(RED + BOLD, "            BANNED IP ADDRESSES"))
    print(ansi(RED + BOLD, "═" * 55))
    for idx, ip in enumerate(banned_ips, 1):
        print(f"  [{idx}] {ip}")
    print(ansi(RED + BOLD, "═" * 55))
    
    unban_choice = input("\nEnter IP number or string to unban (or Enter to go back): ").strip()
    if not unban_choice:
        return

    ip_to_unban = unban_choice
    if unban_choice.isdigit():
        idx = int(unban_choice) - 1
        if 0 <= idx < len(banned_ips):
            ip_to_unban = banned_ips[idx]

    res_unban = tcp_send({"command": "ADMIN_UNBAN_IP", "ip": ip_to_unban})
    if res_unban and res_unban.get("status") == "OK":
        print(ansi(GREEN, f"[OK] IP {ip_to_unban} has been unbanned."))
    else:
        print(ansi(RED, f"[FAILED] Failed to unban IP {ip_to_unban}."))

def display_menu() -> None:
    print("\n" + ansi(CYAN + BOLD, "═" * 55))
    print(ansi(CYAN + BOLD, "  ADMIN PANEL – HEALTHCARE SYSTEM"))
    print(ansi(CYAN + BOLD, "═" * 55))
    print("  " + ansi(YELLOW, "1.") + " View Bookings")
    print("  " + ansi(YELLOW, "2.") + " Remove Booking")
    print("  " + ansi(YELLOW, "3.") + " View Chat History / Kill Session")
    print("  " + ansi(YELLOW, "4.") + " Global Broadcast")
    print("  " + ansi(YELLOW, "5.") + " Security Management")
    print("  " + ansi(RED, "6.") + " Exit")
    print(ansi(CYAN + BOLD, "═" * 55))

def main() -> None:
    if sys.platform == "win32":
        os.system("")  # Enable ANSI color sequences in Windows CMD

    print(ansi(BOLD, "Starting Networked Admin Panel..."), flush=True)
    while True:
        display_menu()
        choice = input("Select option (1-6): ").strip()

        if choice == "1":
            res = tcp_send({"command": "ADMIN_GET_BOOKINGS"})
            if res and res.get("status") == "OK":
                display_bookings(res.get("bookings", {}))

        elif choice == "2":
            res = tcp_send({"command": "ADMIN_GET_BOOKINGS"})
            if res and res.get("status") == "OK":
                remove_booking(res.get("bookings", {}))

        elif choice == "3":
            list_chat_sessions()

        elif choice == "4":
            msg = input("\nEnter broadcast message: ").strip()
            if msg:
                res = tcp_send({"command": "ADMIN_GLOBAL_MSG", "message": msg})
                if res and res.get("status") == "OK":
                    print(ansi(GREEN, "[OK] Message broadcasted successfully!"))
                else:
                    print(ansi(RED, "[FAILED] Failed to broadcast message."))


        elif choice == "5":
            manage_security()

        elif choice == "6":
            print(ansi(GREEN, "\nExiting Admin Panel. Goodbye!"))
            break

        else:
            print(ansi(RED, "Invalid option. Please select 1-6"))

if __name__ == "__main__":
    main()
