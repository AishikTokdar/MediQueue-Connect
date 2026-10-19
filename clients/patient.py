import socket
import json
import sys
import os
import threading
import uuid
import time
import getpass

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "server"))

from crypto_utils import (
    generate_ecdh_keypair,
    derive_ecdh_shared_key,
    decrypt_session_key,
    encrypt_message,
    decrypt_message,
    crypto_available,
    wrap_client_socket,
)
from rudp import send_reliable_message, parse_or_ack
from file_transfer import send_file_stream, FileReceiver

HOST = "127.0.0.1"
PORT = 4000

_session_key: bytes | None = None
_current_session_id: str | None = None


def yn(prompt: str) -> bool:
    return input(prompt).strip().lower() in ("yes", "y")


def banner(text: str) -> None:
    print(f"\n{'='*55}")
    print(f"  {text}")
    print(f"{'='*55}")


from protocol import send_framed, recv_framed


def tcp_send(sock: socket.socket, payload: dict) -> None:
    send_framed(sock, payload)


def tcp_recv(sock: socket.socket) -> dict:
    res = recv_framed(sock)
    if res is None:
        raise ConnectionError("Server disconnected")
    return res


def check_cancel_key() -> bool:
    """Cross-platform non-blocking check to detect if 'c' or 'C' was pressed (Windows & POSIX)."""
    if sys.platform == "win32":
        try:
            import msvcrt
            if msvcrt.kbhit():
                char = msvcrt.getch()
                if char.lower() in (b'c', b'\x03'):
                    return True
        except Exception:
            pass
    else:
        try:
            import select
            import termios
            import tty
            fd = sys.stdin.fileno()
            old_settings = termios.tcgetattr(fd)
            try:
                tty.setcbreak(fd)
                rlist, _, _ = select.select([sys.stdin], [], [], 0)
                if rlist:
                    char = sys.stdin.read(1)
                    if char.lower() in ('c', '\x03'):
                        return True
            finally:
                termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
        except Exception:
            pass
    return False


def show_appointments(tcp: socket.socket, token: str) -> list:
    tcp_send(tcp, {"command": "GET_MY_APPOINTMENTS", "token": token})
    res = tcp_recv(tcp)

    if res.get("status") != "OK":
        print(f"Failed to load appointments: {res.get('reason', 'Unknown error')}")
        return []

    appointments = res.get("appointments", [])
    if not appointments:
        print("\nNo appointments found for your account.")
        return []

    print("\nYour Appointments:")
    for idx, appt in enumerate(appointments, 1):
        date_str = appt.get("appointment_date") or "Today"
        print(
            f"  {idx}. Doctor: {appt.get('doctor', '?'):12} "
            f"[{appt.get('specialization', 'General'):16}]  Date: {date_str:10}  Slot: {appt.get('slot', '?')}"
        )
    return appointments


def cancel_own_appointment(tcp: socket.socket, token: str) -> None:
    appointments = show_appointments(tcp, token)
    if not appointments:
        return

    choice = input("Select appointment number to cancel (or Enter to go back): ").strip()
    if not choice:
        return
    if not choice.isdigit() or not (1 <= int(choice) <= len(appointments)):
        print("Invalid selection.")
        return

    selected = appointments[int(choice) - 1]
    date_label = selected.get('appointment_date', 'today')
    confirm = input(
        f"Cancel appointment with {selected['doctor']} on {date_label} at {selected['slot']}? (yes/no): "
    ).strip().lower()
    if confirm not in ("yes", "y"):
        print("Cancellation aborted.")
        return

    tcp_send(tcp, {
        "command": "CANCEL_MY_BOOKING",
        "token": token,
        "doctor": selected["doctor"],
        "slot": selected["slot"],
        "appointment_date": selected.get("appointment_date"),
    })
    res = tcp_recv(tcp)
    if res.get("status") == "OK":
        print("[OK] Appointment cancelled successfully.")

    else:
        print(f"Cancellation failed: {res.get('reason', 'Unknown error')}")


def show_prescriptions(tcp: socket.socket, token: str) -> None:
    tcp_send(tcp, {"command": "GET_MY_PRESCRIPTIONS", "token": token})
    res = tcp_recv(tcp)
    if res.get("status") != "OK":
        print(f"Failed to load prescriptions: {res.get('reason', 'Unknown error')}")
        return
    rx_list = res.get("prescriptions", [])
    if not rx_list:
        print("\nNo digital prescriptions found on file for your account.")
        return
    print("\n" + "=" * 65)
    print("                     YOUR DIGITAL PRESCRIPTIONS (Rx)")
    print("=" * 65)
    for idx, rx in enumerate(rx_list, 1):
        created = rx.get("created_at", "N/A")
        doc = rx.get("doctor", "Unknown")
        diag = rx.get("diagnosis", "Unspecified")
        print(f"\n[{idx}] Date: {created} | Prescribed by: Dr. {doc}")
        print(f"    Diagnosis: {diag}")
        inst = rx.get("instructions")
        if inst:
            print(f"    Advice: {inst}")
        meds = rx.get("medications", [])
        if meds:
            print("    Medications:")
            for m in meds:
                print(f"      - {m.get('name')}: {m.get('dosage')} | {m.get('frequency')} for {m.get('duration')}")
    print("=" * 65)


def manage_profile(tcp: socket.socket, token: str) -> None:
    tcp_send(tcp, {"command": "GET_PROFILE", "token": token})
    res = tcp_recv(tcp)
    prof = res.get("profile", {})
    
    print("\n" + "=" * 55)
    print("           PATIENT CLINICAL HEALTH PROFILE")
    print("=" * 55)
    print(f"  Date of Birth     : {prof.get('dob') or 'Not specified'}")
    print(f"  Blood Group       : {prof.get('blood_group') or 'Not specified'}")
    allergies = prof.get("allergies", [])
    print(f"  Known Allergies   : {', '.join(allergies) if allergies else 'None reported'}")
    conditions = prof.get("chronic_conditions", [])
    print(f"  Chronic Conditions: {', '.join(conditions) if conditions else 'None reported'}")
    print(f"  Emergency Contact : {prof.get('emergency_contact') or 'Not specified'}")
    print("=" * 55)

    if not yn("Do you want to update your profile details? (yes/no): "):
        return

    dob = input(f"Date of Birth (YYYY-MM-DD) [{prof.get('dob', '')}]: ").strip() or prof.get("dob", "")
    bg = input(f"Blood Group (e.g., A+, O-, B+) [{prof.get('blood_group', '')}]: ").strip() or prof.get("blood_group", "")
    current_all = ", ".join(allergies)
    all_in = input(f"Known Drug/Food Allergies (comma-separated) [{current_all}]: ").strip()
    new_all = [a.strip() for a in all_in.split(",") if a.strip()] if all_in else allergies
    current_cond = ", ".join(conditions)
    cond_in = input(f"Chronic Medical Conditions (comma-separated) [{current_cond}]: ").strip()
    new_cond = [c.strip() for c in cond_in.split(",") if c.strip()] if cond_in else conditions
    contact = input(f"Emergency Contact Number [{prof.get('emergency_contact', '')}]: ").strip() or prof.get("emergency_contact", "")

    tcp_send(tcp, {
        "command": "UPDATE_PROFILE",
        "token": token,
        "dob": dob,
        "blood_group": bg,
        "allergies": new_all,
        "chronic_conditions": new_cond,
        "emergency_contact": contact,
    })
    update_res = tcp_recv(tcp)
    if update_res.get("status") == "OK":
        print("[OK] Clinical health profile updated successfully.")
    else:
        print(f"Failed to update profile: {update_res.get('reason', 'Unknown error')}")


def main():  # noqa: C901
    banner("Healthcare System  -  Welcome")


    tcp = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        tcp.connect((HOST, PORT))
        tcp = wrap_client_socket(tcp, server_hostname=HOST)
    except ConnectionRefusedError:
        print("\nHealth Server stopped")
        sys.exit(1)

    def heartbeat():
        while True:
            time.sleep(2)
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.settimeout(2)
                s.connect((HOST, PORT))
                s = wrap_client_socket(s, server_hostname=HOST)
                s.close()
            except Exception:
                print("\nHealth Server stopped", flush=True)
                os._exit(1)

    threading.Thread(target=heartbeat, daemon=True).start()

    username = None

    while True:
        print("\nStartup Menu:")
        print("  1. Login")
        print("  2. Register")
        print("  3. Exit")
        choice = input("Select an option (1-3): ").strip()

        if choice == "3":
            tcp.close()
            print("Goodbye!")
            sys.exit(0)
            
        elif choice == "1":
            username = input("Enter username: ").strip()
            password = getpass.getpass("Password: ")
            tcp_send(tcp, {"command": "LOGIN", "username": username, "password": password})
            res = tcp_recv(tcp)

            if res["status"] == "OK":
                break
            print(f"  Login failed: {res.get('reason', 'Invalid credentials.')}\n")
            
        elif choice == "2":
            username = input("Choose a new username: ").strip()
            password = getpass.getpass("Choose a secure password: ")
            ins_input = input("Enter supported insurances (comma-separated, e.g., 'insuranceA, insuranceB'): ").strip()
            insurances = [i.strip() for i in ins_input.split(',')] if ins_input else []
            
            tcp_send(tcp, {"command": "REGISTER", "username": username, "password": password, "insurance": insurances})
            res = tcp_recv(tcp)
            
            if res["status"] == "OK":
                if "token" not in res:
                    tcp_send(tcp, {"command": "LOGIN", "username": username, "password": password})
                    res = tcp_recv(tcp)
                break
            print(f"  Registration failed: {res.get('reason', 'unknown')}.\n")
            
        else:
            print("Invalid option. Please try again.")

    token = res["token"]
    insurance = res.get("insurance", [])
    print(f"\n  Logged in as {username}  [OK]   (token: {token[:8]}...)")

    if insurance:
        print(f"  Insurance: {', '.join(insurance)}")

    def push_subscriber():
        try:
            sub = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sub.connect((HOST, PORT))
            sub = wrap_client_socket(sub, server_hostname=HOST)
            tcp_send(sub, {"command": "SUBSCRIBE", "token": token})
            while True:
                msg = recv_framed(sub)
                if not msg:
                    break
                if msg.get("status") == "GLOBAL_MSG":
                    print(f"\n\033[1m\033[93m[SERVER BROADCAST] {msg.get('message')}\033[0m", flush=True)
                elif msg.get("status") == "KILL_SESSION":
                    if msg.get("session_id") == _current_session_id:
                        print("\n\033[1m\033[91m[SERVER] FORCE TERMINATED SESSION\033[0m", flush=True)
                        os._exit(0)
        except Exception:
            pass

    threading.Thread(target=push_subscriber, daemon=True).start()

    doctor = None
    udp_port = None

    while True:
        print("\nMain Menu:")
        print("  1. Book appointment")
        print("  2. Chat with doctor")
        print("  3. Show appointments")
        print("  4. Remove my appointment")
        print("  5. View my digital prescriptions (Rx)")
        print("  6. Manage health profile & medical history")
        print("  7. Exit")
        choice = input("Select an option (1-7): ").strip()

        if choice == "7":
            tcp.close()
            print("Goodbye!")
            sys.exit(0)

        elif choice == "6":
            manage_profile(tcp, token)
            continue

        elif choice == "5":
            show_prescriptions(tcp, token)
            continue
            
        elif choice == "1":
            tcp_send(tcp, {"command": "GET_SPECIALIZATIONS", "token": token})
            spec_res = tcp_recv(tcp)
            specs = spec_res.get("specializations", [])

            print("\nWhat type of doctor would you like to see?")
            print("Select Specialization:")
            for idx, s in enumerate(specs, 1):
                print(f"  {idx}. {s}")
            print("  0. All Specializations")

            while True:
                spec_choice = input("Filter by specialization (number or 0 for All): ").strip()
                chosen_spec = None
                if spec_choice == "0":
                    break
                if spec_choice.isdigit() and 1 <= int(spec_choice) <= len(specs):
                    chosen_spec = specs[int(spec_choice) - 1]
                    print(f"  Filtering for: {chosen_spec}")
                    break
                print("  Invalid option. Please enter a valid number.")

            tcp_send(tcp, {
                "command": "GET_SLOTS",
                "token": token,
                "specialization": chosen_spec,
            })
            slots = tcp_recv(tcp)

            if not slots:
                print("\nNo available slots match your insurance coverage and specialization criteria.")
                continue

            print("\nMatching Doctors & Available Slots (Covered by your Insurance Policy):")
            doc_list = list(slots.keys())
            for idx, doc_name in enumerate(doc_list, 1):
                info = slots[doc_name]
                acc_ins = ", ".join(info.get("accepted_insurance", []))
                print(f"  {idx}. {doc_name:12}  [{info.get('specialization', 'General Physician'):20}]  (Insurance: {acc_ins:22})  Slots: {', '.join(info['slots'])}")

            while True:
                doctor_input = input("Select doctor (name or number): ").strip()
                doctor = doctor_input
                if doctor_input.isdigit():
                    idx = int(doctor_input)
                    if 1 <= idx <= len(doc_list):
                        doctor = doc_list[idx - 1]
                        break
                elif doctor in doc_list:
                    break
                print("  Invalid selection. Please try again.")
            today_str = time.strftime("%Y-%m-%d")
            appt_date = input(f"Select appointment date (YYYY-MM-DD) [default: {today_str}]: ").strip() or today_str
            slot = input("Select time slot:    ").strip()

            tcp_send(tcp, {
                "command": "BOOK_SLOT",
                "token": token,
                "doctor": doctor,
                "slot": slot,
                "appointment_date": appt_date,
            })
            res = tcp_recv(tcp)

            if res["status"] != "BOOKED":
                print(f"Booking failed: {res.get('reason', 'slot unavailable')}")
                continue

            udp_port = res["udp_port"]
            confirmed_date = res.get("appointment_date", appt_date)
            print(f"\n  [OK] Appointment booked with Dr. {doctor} on {confirmed_date} at {slot}")


            if not yn("Do you want to chat with the doctor now? (yes/no): "):
                continue
            
            break

        elif choice == "2":
            tcp_send(tcp, {"command": "GET_SPECIALIZATIONS", "token": token})
            spec_res = tcp_recv(tcp)
            specs = spec_res.get("specializations", [])

            print("\nWhat type of doctor would you like to consult with?")
            print("Select Specialization:")
            for idx, s in enumerate(specs, 1):
                print(f"  {idx}. {s}")
            print("  0. All Specializations")

            while True:
                spec_choice = input("Filter by specialization (number or 0 for All): ").strip()
                chosen_spec = None
                if spec_choice == "0":
                    break
                if spec_choice.isdigit() and 1 <= int(spec_choice) <= len(specs):
                    chosen_spec = specs[int(spec_choice) - 1]
                    print(f"  Filtering for: {chosen_spec}")
                    break
                print("  Invalid option. Please enter a valid number.")

            tcp_send(tcp, {"command": "GET_DOCTORS", "token": token, "specialization": chosen_spec})
            doc_res = tcp_recv(tcp)
            
            if doc_res["status"] != "OK":
                print("Failed to GET_DOCTORS.")
                tcp.close()
                sys.exit(1)

            all_doctors = doc_res.get("doctors", {})

            if not all_doctors:
                print("\nNo doctors match your insurance coverage and specialization criteria.")
                continue

            sorted_docs = sorted(
                all_doctors.items(),
                key=lambda x: (not x[1].get("online", False), x[1].get("specialization", "").lower(), x[0].lower())
            )

            print("\nMatching Doctors (Covered by your Insurance Policy):")
            for idx, (d, info) in enumerate(sorted_docs, 1):
                status = "Online" if info.get("online", False) else "Offline"
                acc_ins = ", ".join(info.get("accepted_insurance", []))
                rating = info.get("average_rating", 5.0)
                reviews_cnt = info.get("total_reviews", 0)
                rating_str = f"★ {rating:.1f} ({reviews_cnt} reviews)"
                print(f"  {idx}. {d:12}  [{info.get('specialization','General Physician'):18}]  ({status:7})  {rating_str:18}  Insurance: {acc_ins}")

            while True:
                doctor_input = input("Choose doctor (name or number): ").strip()
                doctor = doctor_input
                if doctor_input.isdigit():
                    idx = int(doctor_input)
                    if 1 <= idx <= len(sorted_docs):
                        doctor = sorted_docs[idx - 1][0]
                        break
                elif doctor in [d for d, _ in sorted_docs]:
                    break
                print("  Invalid selection. Please try again.")

            if doctor not in all_doctors:
                tcp.close()
                print("Doctor not found.")
                sys.exit(1)

            udp_port = all_doctors[doctor]["udp_port"]
            break

        elif choice == "3":
            show_appointments(tcp, token)

        elif choice == "4":
            cancel_own_appointment(tcp, token)

        else:
            print("Invalid option. Please try again.")
            continue

    global _current_session_id
    _current_session_id = str(uuid.uuid4())
    session_id = _current_session_id

    print("\nSelect Consultation Urgency (ESI Triage):")
    print("  1. ESI-1: Immediate / Resuscitation")
    print("  2. ESI-2: Emergent / Severe Pain")
    print("  3. ESI-3: Urgent / Acute Symptoms")
    print("  4. ESI-4: Less Urgent / Minor Ailment")
    print("  5. ESI-5: Routine Consultation (Default)")
    triage_in = input("Select Urgency [1-5, default 5]: ").strip()
    esi_level = int(triage_in) if triage_in in ("1", "2", "3", "4", "5") else 5

    print(f"\nRequesting consultation with {doctor} (ESI-{esi_level})...")
    tcp_send(tcp, {
        "command": "REQUEST_CHAT",
        "token": token,
        "doctor": doctor,
        "session_id": session_id,
        "esi_level": esi_level,
    })

    res = tcp_recv(tcp)

    if res["status"] == "QUEUED":
        pos = res.get("position", "?")
        print(f"\n  Doctor is busy. You are #{pos} in the queue [Triage: ESI-{esi_level}].")
        print("  Waiting... (Press 'c' to leave the queue)\n")

        while True:
            tcp.settimeout(0.5)
            try:
                res = tcp_recv(tcp)
                break
            except socket.timeout:
                pass
            except ConnectionError:
                print("Server disconnected.")
                tcp.close()
                sys.exit(1)

            if check_cancel_key():
                tcp.settimeout(None)
                tcp_send(tcp, {"command": "CANCEL_QUEUE", "token": token, "doctor": doctor})
                tcp_recv(tcp)
                print("\nQueue cancelled. Goodbye!")
                tcp.close()
                sys.exit(0)

        tcp.settimeout(None)

    if res["status"] == "TURN_READY":
        udp_port = res["udp_port"]
        print(f"\n  [OK] Doctor is now available! Connecting...")
    elif res["status"] == "READY":
        udp_port = res["udp_port"]
        print(f"\n  [OK] Doctor is free! Connecting...")
    elif res["status"] != "READY":
        print(f"Chat request failed: {res}")
        tcp.close()
        sys.exit(1)

    udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    udp.settimeout(15.0)

    print(f"\nConnecting to {doctor} on UDP port {udp_port}...")

    ecdh_priv = None
    hello_payload = {
        "type": "HELLO",
        "patient": username,
        "session_id": session_id,
        "esi_level": esi_level,
    }
    if crypto_available():
        try:
            ecdh_priv, pub_b64 = generate_ecdh_keypair()
            hello_payload["public_key"] = pub_b64
        except Exception:
            ecdh_priv = None

    udp.sendto(json.dumps(hello_payload).encode(), (HOST, udp_port))

    try:
        raw, _ = udp.recvfrom(4096)
    except socket.timeout:
        print("Doctor did not respond in time. They may be offline.")
        udp.close()
        tcp.close()
        sys.exit(1)
    except (ConnectionResetError, ConnectionRefusedError, OSError):
        print("Doctor is currently unresponsive or offline.")
        udp.close()
        tcp.close()
        sys.exit(1)

    handshake = json.loads(raw.decode())

    global _session_key
    _session_key = None

    if handshake["type"] == "KEY_EXCHANGE":
        if "public_key" in handshake and ecdh_priv is not None:
            try:
                _session_key = derive_ecdh_shared_key(ecdh_priv, handshake["public_key"])
                print("  [ENCRYPTED - ECDH X25519] Ephemeral session key negotiated with Perfect Forward Secrecy.")
            except Exception as e:
                print(f"  [WARN] ECDH key derivation failed: {e}. Falling back.")
        elif "encrypted_key" in handshake:
            enc_key = handshake["encrypted_key"]
            try:
                _session_key = decrypt_session_key(enc_key)
                print("  [ENCRYPTED - Legacy Passphrase] Session established")
            except Exception as e:
                print(f"  [WARN] Key decryption failed: {e}. Using plaintext.")
    elif handshake["type"] == "READY":
        print("  Chat session established (no encryption).")
    elif handshake["type"] == "BUSY":
        print("  Doctor is currently busy. Please retry.")
        udp.close()
        tcp.close()
        sys.exit(1)
    else:
        print(f"  Unexpected handshake: {handshake}")
        udp.close()
        tcp.close()
        sys.exit(1)

    tcp_send(tcp, {
        "command": "START_CHAT",
        "token": token,
        "doctor": doctor,
        "session_id": session_id,
    })
    tcp_recv(tcp)

    udp.settimeout(None)

    enc_label = "[ENCRYPTED]" if _session_key else "[PLAINTEXT]"
    print(f"\n  {enc_label} chat with Dr. {doctor} started.")
    print("  Type 'exit' to end, or '/sendfile <path>' to transfer lab reports/attachments.\n")

    transcript: list[dict] = []
    file_receiver = FileReceiver()

    while True:
        try:
            msg = input("You: ").strip()
        except EOFError:
            msg = "exit"

        if msg.lower() == "exit":
            udp.sendto(json.dumps({"type": "EXIT"}).encode(), (HOST, udp_port))
            _end_session(tcp, token, doctor, session_id, username=username, transcript=transcript)
            print("Chat ended. Goodbye!")
            break

        if msg.startswith("/sendfile "):
            filepath = msg.split(" ", 1)[1].strip()
            send_file_stream(udp, (HOST, udp_port), filepath, session_id, session_key=_session_key, send_fn=send_reliable_message)
            continue

        now_ts = time.strftime("%Y-%m-%d %H:%M:%S")
        transcript.append({"sender": username, "text": msg, "ts": now_ts})

        cipher = encrypt_message(msg, _session_key) if _session_key else msg
        send_reliable_message(udp, {"type": "CHAT", "text": cipher}, (HOST, udp_port))

        try:
            raw, _ = udp.recvfrom(4096)
        except socket.timeout:
            print("[Doctor did not reply in time]")
            continue

        reply = parse_or_ack(udp, raw, (HOST, udp_port))

        if reply.get("type") in ("FILE_START", "FILE_CHUNK", "FILE_END"):
            saved_path = file_receiver.process_packet(reply, session_id, session_key=_session_key)
            if saved_path:
                print(f"\n  [FILE RECEIVED from Dr. {doctor}] Saved to:\n    {saved_path}")
            continue

        if reply.get("type") == "EXIT":
            print("\n  Doctor ended the session.")
            _end_session(tcp, token, doctor, session_id, username=username, transcript=transcript)
            break

        if reply.get("type") == "CHAT":
            cipher_reply = reply.get("text", "")
            plaintext = decrypt_message(cipher_reply, _session_key) if _session_key else cipher_reply
            reply_ts = time.strftime("%Y-%m-%d %H:%M:%S")
            transcript.append({"sender": doctor, "text": plaintext, "ts": reply_ts})
            print(f"Doctor: {plaintext}")

    udp.close()
    tcp.close()


def _end_session(tcp: socket.socket, token: str, doctor: str, session_id: str, username: str = "patient", transcript: list[dict] | None = None) -> None:
    try:
        payload = {
            "command": "END_SESSION",
            "token": token,
            "doctor": doctor,
            "session_id": session_id,
            "patient": username,
        }
        if transcript:
            payload["transcript"] = transcript
        tcp_send(tcp, payload)
        tcp_recv(tcp)
    except Exception:
        pass

    try:
        want_review = input(f"\nWould you like to rate your consultation with Dr. {doctor}? (yes/no): ").strip().lower()
        if want_review in ("yes", "y"):
            r_in = input("Rate your experience (1-5 stars) [default 5]: ").strip()
            rating = int(r_in) if r_in in ("1", "2", "3", "4", "5") else 5
            comment = input("Leave feedback or review notes (optional): ").strip()
            tcp_send(tcp, {
                "command": "SUBMIT_REVIEW",
                "token": token,
                "doctor": doctor,
                "rating": rating,
                "review": comment,
                "session_id": session_id,
            })
            rev_res = tcp_recv(tcp)
            if rev_res and rev_res.get("status") == "OK":
                stats = rev_res.get("stats", {})
                print(f"  [OK] Thank you! Review submitted. Dr. {doctor} average rating is now ★ {stats.get('average_rating', 5.0)}.")
    except Exception as e:
        print(f"  Notice: Could not submit review: {e}")

    try:
        want_pdf = input("\nDo you want to export a formatted PDF summary of this consultation? (yes/no): ").strip().lower()
        if want_pdf in ("yes", "y"):
            print("  Generating PDF transcript summary via background task queue...")
            tcp_send(tcp, {
                "command": "GENERATE_TRANSCRIPT_PDF",
                "token": token,
                "session_id": session_id,
                "doctor": doctor,
            })
            res = tcp_recv(tcp)
            if res.get("status") == "OK":
                pdf_path = res.get("pdf_path", "data/summaries/")
                print(f"  [OK] PDF transcript summary successfully exported to:\n    {pdf_path}")

            else:
                print(f"  Failed to generate PDF summary: {res.get('reason', 'Unknown error')}")
    except Exception as e:
        print(f"  Notice: Could not complete PDF export request: {e}")



if __name__ == "__main__":
    main()
