import socket
import json
import sys
import os
import threading
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "server"))

from crypto_utils import (
    generate_ecdh_keypair,
    derive_ecdh_shared_key,
    generate_session_key,
    encrypt_session_key,
    decrypt_session_key,
    decrypt_message,
    encrypt_message,
    crypto_available,
    wrap_client_socket,
)
from rudp import send_reliable_message, parse_or_ack
from file_transfer import send_file_stream, FileReceiver

HOST = "127.0.0.1"
SERVER_PORT = 4000

_current_session_id = None
_doctor_token = "DOCTOR_INTERNAL"


from protocol import send_framed, recv_framed


def send_tcp(payload: dict) -> dict | None:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.connect((HOST, SERVER_PORT))
        s = wrap_client_socket(s, server_hostname=HOST)
        send_framed(s, payload)
        resp = recv_framed(s)
        s.close()
        return resp
    except Exception as e:
        print(f"[WARN] TCP to server failed: {e}")
        return None


def display_clinical_intake(patient_name: str, esi_level: int = 5) -> None:
    global _doctor_token
    res = send_tcp({
        "command": "GET_PATIENT_INTAKE",
        "doctor": "doctor",
        "token": _doctor_token,
        "patient": patient_name,
    })
    prof = res.get("profile", {}) if res else {}
    esi_names = {
        1: "ESI-1: CRITICAL / RESUSCITATION",
        2: "ESI-2: EMERGENT",
        3: "ESI-3: URGENT",
        4: "ESI-4: LESS URGENT",
        5: "ESI-5: ROUTINE",
    }
    triage_str = esi_names.get(esi_level, "ESI-5: ROUTINE")
    print("+" + "-" * 62 + "+")
    print(f"|  CLINICAL INTAKE CARD: {patient_name:40} |")
    print(f"|  TRIAGE SEVERITY: {triage_str:44} |")
    print("+" + "-" * 62 + "+")
    dob = prof.get("dob") or "Unknown"
    bg = prof.get("blood_group") or "Not recorded"
    print(f"|  DOB: {dob:20} Blood Group: {bg:24} |")
    allergies = prof.get("allergies", [])
    all_str = ", ".join(allergies).upper() if allergies else "NONE RECORDED"
    print(f"|  ALLERGIES (ALERT): {all_str:41} |")
    conditions = prof.get("chronic_conditions", [])
    cond_str = ", ".join(conditions) if conditions else "None recorded"
    print(f"|  Chronic Conditions: {cond_str:40} |")
    contact = prof.get("emergency_contact") or "Not provided"
    print(f"|  Emergency Contact : {contact:40} |")
    print("+" + "-" * 62 + "+\n")


def register_new_doctor_flow(preset_name: str | None = None) -> tuple[str, dict]:
    print("\n=======================================================")
    print("           REGISTER NEW DOCTOR PROFILE")
    print("=======================================================")
    
    if preset_name:
        doctor_name = preset_name
        print(f"Doctor ID/Name: {doctor_name}")
    else:
        while True:
            doctor_name = input("Enter Doctor Name/ID (e.g., doctor7, Dr. Sarah): ").strip()
            if doctor_name:
                break

    specs = ["General Physician", "Cardiologist", "Dermatologist", "Neurologist", "Orthopedic", "Pediatrician"]
    print("\nSelect Specialization:")
    for idx, s in enumerate(specs, 1):
        print(f"  {idx}. {s}")
    print(f"  {len(specs)+1}. Custom Specialization")

    while True:
        choice = input(f"Select specialization (1-{len(specs)+1}): ").strip()
        if choice.isdigit():
            idx = int(choice)
            if 1 <= idx <= len(specs):
                specialization = specs[idx - 1]
                break
            elif idx == len(specs) + 1:
                specialization = input("Enter custom specialization: ").strip() or "General Physician"
                break
        print("Invalid choice. Please try again.")

    print("\nSelect Accepted Insurance Policies:")
    print("  1. insuranceA only")
    print("  2. insuranceB only")
    print("  3. Both insuranceA & insuranceB")
    
    insurance_map = {
        "1": ["insuranceA"],
        "2": ["insuranceB"],
        "3": ["insuranceA", "insuranceB"],
    }
    while True:
        ins_choice = input("Select insurance option (1-3): ").strip()
        if ins_choice in insurance_map:
            accepted_insurance = insurance_map[ins_choice]
            break
        print("Invalid choice. Please enter 1, 2, or 3.")

    data_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "doctors.json")
    try:
        with open(data_path) as f:
            existing_docs = json.load(f)
        existing_ports = [d["udp_port"] for d in existing_docs.values() if "udp_port" in d]
        default_port = (max(existing_ports) + 1) if existing_ports else 5001
    except Exception:
        default_port = 5001

    port_input = input(f"Enter UDP listening port (default: {default_port}): ").strip()
    udp_port = int(port_input) if port_input.isdigit() else default_port

    reg_res = send_tcp({
        "command": "REGISTER_DOCTOR",
        "doctor": doctor_name,
        "specialization": specialization,
        "accepted_insurance": accepted_insurance,
        "udp_port": udp_port,
        "slots": ["9AM", "11AM", "2PM", "4PM"],
    })

    if not reg_res or reg_res.get("status") != "OK":
        print(f"Error registering doctor: {reg_res}")
        sys.exit(1)

    print(f"\n[OK] Doctor '{doctor_name}' registered successfully!")

    return doctor_name, {
        "udp_port": udp_port,
        "specialization": specialization,
        "accepted_insurance": accepted_insurance,
    }


def main():
    data_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "doctors.json")
    try:
        with open(data_path) as f:
            doctors = json.load(f)
    except Exception:
        doctors = {}

    if len(sys.argv) >= 2:
        doctor_name = sys.argv[1]
        if doctor_name in doctors:
            info = doctors[doctor_name]
        else:
            doctor_name, info = register_new_doctor_flow(preset_name=doctor_name)
    else:
        print("\n=======================================================")
        print("           MediQueue Connect - Doctor Portal")
        print("=======================================================")
        print("  1. Select registered doctor")
        print("  2. Register new doctor")
        choice = input("Select an option (1-2): ").strip()
        
        if choice == "2":
            doctor_name, info = register_new_doctor_flow()
        else:
            doc_list = list(doctors.keys())
            if not doc_list:
                print("No registered doctors found. Creating new doctor profile...")
                doctor_name, info = register_new_doctor_flow()
            else:
                print("\nRegistered Doctors:")
                for idx, d in enumerate(doc_list, 1):
                    doc_info = doctors[d]
                    print(f"  {idx}. {d:12} [{doc_info.get('specialization', 'General Physician')}] (Insurances: {', '.join(doc_info.get('accepted_insurance', []))})")
                
                while True:
                    d_input = input("Select doctor (number or name): ").strip()
                    if d_input.isdigit() and 1 <= int(d_input) <= len(doc_list):
                        doctor_name = doc_list[int(d_input) - 1]
                        info = doctors[doctor_name]
                        break
                    elif d_input in doctors:
                        doctor_name = d_input
                        info = doctors[doctor_name]
                        break
                    print("Invalid selection. Please try again.")

    global _doctor_token
    default_pwd = f"{doctor_name}123"
    print(f"\n[AUTHENTICATION] Sign in as Dr. {doctor_name}")
    pwd_input = input(f"Enter password [default: {default_pwd}]: ").strip() or default_pwd
    login_res = send_tcp({
        "command": "DOCTOR_LOGIN",
        "doctor": doctor_name,
        "password": pwd_input,
    })
    if login_res and login_res.get("status") == "OK":
        _doctor_token = login_res.get("token", "DOCTOR_INTERNAL")
        print(f"[OK] Doctor '{doctor_name}' authenticated successfully! (Role: {login_res.get('role', 'doctor')})")
    else:
        err = login_res.get("reason") if login_res else "No server response"
        print(f"[WARN] Doctor authentication warning: {err}. Using local session.")

    udp_port = info["udp_port"]
    specialization = info.get("specialization", "General Physician")
    accepted_insurance = info.get("accepted_insurance", [])

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((HOST, udp_port))

    print(f"\n{'='*55}")
    print(f"  Dr. {doctor_name}  -  {specialization}")
    print(f"  UDP port: {udp_port}")

    print(f"{'='*55}")
    print("  Waiting for patients...\n")

    global _current_session_id
    peers = {}

    res = send_tcp({
        "command": "DOCTOR_ONLINE",
        "token": _doctor_token,
        "doctor": doctor_name
    })
    
    if res is None:
        print("\nHealth Server stopped")
        sys.exit(1)

    def push_subscriber():
        try:
            sub = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sub.connect((HOST, SERVER_PORT))
            sub = wrap_client_socket(sub, server_hostname=HOST)
            send_framed(sub, {"command": "SUBSCRIBE", "token": _doctor_token})
            while True:
                msg = recv_framed(sub)
                if not msg:
                    break
                if msg.get("status") == "GLOBAL_MSG":
                    print(f"\n\033[1m\033[93m[SERVER BROADCAST] {msg.get('message')}\033[0m", flush=True)
                elif msg.get("status") == "KILL_SESSION":
                    if _current_session_id and msg.get("session_id") == _current_session_id:
                        print("\n\033[1m\033[91m[SERVER] FORCE TERMINATED SESSION\033[0m", flush=True)
                        _notify_server_end(doctor_name, _current_session_id)
                        os._exit(0)
        except Exception:
            print("\nHealth Server stopped (push connection lost)", flush=True)
            os._exit(1)

    threading.Thread(target=push_subscriber, daemon=True).start()
    file_receiver = FileReceiver()

    try:
        while True:
            try:
                data, addr = sock.recvfrom(4096)
                msg = parse_or_ack(sock, data, addr)
                if not msg or "type" not in msg:
                    continue

                if msg["type"] in ("FILE_START", "FILE_CHUNK", "FILE_END") and addr in peers:
                    s_key = peers[addr].get("session_key")
                    saved_path = file_receiver.process_packet(msg, _current_session_id or "general", session_key=s_key)
                    if saved_path:
                        print(f"\n  [CLINICAL ATTACHMENT/LAB REPORT RECEIVED] Saved to:\n    {saved_path}\n")
                    continue

                if msg["type"] == "HELLO":
                    if peers and _current_session_id and msg.get("session_id", "") != _current_session_id:
                        sock.sendto(json.dumps({"type": "BUSY"}).encode(), addr)
                        continue

                    patient_name = msg.get("patient", "peer")
                    _current_session_id = msg.get("session_id", "unknown")
                    
                    s_key = None
                    if crypto_available():
                        if "public_key" in msg:
                            try:
                                doc_priv, doc_pub_b64 = generate_ecdh_keypair()
                                s_key = derive_ecdh_shared_key(doc_priv, msg["public_key"])
                                sock.sendto(json.dumps({
                                    "type": "KEY_EXCHANGE",
                                    "public_key": doc_pub_b64,
                                    "session_id": _current_session_id,
                                }).encode(), addr)
                                print(f"  [ENCRYPTED - ECDH X25519] Ephemeral key negotiated with {patient_name}")
                            except Exception as e:
                                print(f"  [WARN] ECDH key exchange failed: {e}")
                                s_key = None
                        if s_key is None:
                            s_key = generate_session_key()
                            enc_key = encrypt_session_key(s_key)
                            sock.sendto(json.dumps({
                                "type": "KEY_EXCHANGE",
                                "encrypted_key": enc_key,
                                "session_id": _current_session_id,
                            }).encode(), addr)
                    else:
                        sock.sendto(json.dumps({
                            "type": "READY",
                            "session_id": _current_session_id,
                        }).encode(), addr)

                    esi_level = msg.get("esi_level", 5)
                    peers[addr] = {"name": patient_name, "session_key": s_key, "transcript": []}
                    print(f"\n[SESSION STARTED/JOINED] {patient_name}  ID: {_current_session_id}\n")
                    display_clinical_intake(patient_name, esi_level=esi_level)

                elif msg["type"] == "KEY_EXCHANGE":
                    enc_key = msg.get("encrypted_key")
                    s_key = decrypt_session_key(enc_key) if enc_key else None
                    peer_name = "Doctor (Invited)"
                    peers[addr] = {"name": peer_name, "session_key": s_key, "transcript": []}
                    print(f"\n[JOINED] {peer_name}\n")
                    
                elif msg["type"] == "READY":
                    peer_name = "Doctor (Invited - Plain)"
                    peers[addr] = {"name": peer_name, "session_key": None, "transcript": []}
                    print(f"\n[JOINED] {peer_name}\n")

                elif msg["type"] == "CHAT" and addr in peers:
                    p_info = peers[addr]
                    s_key = p_info["session_key"]
                    p_name = p_info["name"]
                    
                    ciphertext = msg["text"]
                    plaintext = decrypt_message(ciphertext, s_key) if s_key else ciphertext

                    msg_ts = time.strftime("%Y-%m-%d %H:%M:%S")
                    p_info.setdefault("transcript", []).append({"sender": p_name, "text": plaintext, "ts": msg_ts})

                    print(f"\n[{p_name}]: {plaintext}")
                    
                    for peer_addr, peer_info in peers.items():
                        if peer_addr != addr:
                            other_key = peer_info["session_key"]
                            forward_msg = f"[{p_name}] {plaintext}"
                            f_cipher = encrypt_message(forward_msg, other_key) if other_key else forward_msg
                            sock.sendto(json.dumps({"type": "CHAT", "text": f_cipher}).encode(), peer_addr)

                    reply = input("Reply (or /invite <doc> /sendfile <path>): ").strip()

                    if reply.startswith("/sendfile "):
                        filepath = reply.split(" ", 1)[1].strip()
                        for peer_addr, peer_info in peers.items():
                            send_file_stream(sock, peer_addr, filepath, _current_session_id or "general", session_key=peer_info.get("session_key"), send_fn=send_reliable_message)
                        continue

                    if reply.startswith("/invite "):
                        target_doc = reply.split()[1]
                        if target_doc in doctors:
                            t_port = doctors[target_doc]["udp_port"]
                            sock.sendto(json.dumps({
                                "type": "HELLO",
                                "patient": doctor_name,
                                "session_id": _current_session_id,
                            }).encode(), (HOST, t_port))
                            print(f"[INVITED {target_doc}]")
                        else:
                            print(f"[ERROR] Doctor {target_doc} not found.")
                        continue

                    if reply.lower() == "exit":
                        for peer_addr in list(peers.keys()):
                            sock.sendto(json.dumps({"type": "EXIT"}).encode(), peer_addr)
                        print("\n[SESSION ENDED by doctor]\n")
                        active_transcript = p_info.get("transcript", [])
                        _notify_server_end(doctor_name, _current_session_id, patient_name=p_name, transcript=active_transcript)
                        peers.clear()
                        _current_session_id = None
                        continue

                    reply_ts = time.strftime("%Y-%m-%d %H:%M:%S")
                    p_info.setdefault("transcript", []).append({"sender": doctor_name, "text": reply, "ts": reply_ts})

                    for peer_addr, peer_info in peers.items():
                        my_cipher = encrypt_message(reply, peer_info["session_key"]) if peer_info["session_key"] else reply
                        send_reliable_message(sock, {"type": "CHAT", "text": my_cipher}, peer_addr)

                elif msg["type"] == "EXIT" and addr in peers:
                    p_info = peers[addr]
                    p_name = p_info["name"]
                    active_transcript = p_info.get("transcript", [])
                    print(f"\n[{p_name} LEFT SESSION]\n")
                    del peers[addr]
                    if not peers:
                        _notify_server_end(doctor_name, _current_session_id, patient_name=p_name, transcript=active_transcript)
                        _current_session_id = None
                        print("\n[SESSION EMPTY -> ENDED]\n")

            except OSError as e:
                if (hasattr(e, "winerror") and e.winerror == 10054) or getattr(e, "errno", None) in (104, 111):
                    continue  # Windows & Linux ICMP port-unreachable; safe to ignore
                print(f"[OSError] {e}")
            except Exception as e:
                print(f"[ERROR] {e}")

    except KeyboardInterrupt:
        pass
    finally:
        print("\n[DOCTOR OFFLINE] Shutting down...")
        send_tcp({
            "command": "DOCTOR_OFFLINE",
            "token": "DOCTOR_INTERNAL",
            "doctor": doctor_name
        })
        sock.close()


def _notify_server_end(doctor_name: str, session_id: str | None, patient_name: str = "patient", transcript: list[dict] | None = None) -> None:
    if session_id:
        end_payload = {
            "command": "END_SESSION",
            "token": "DOCTOR_INTERNAL",
            "doctor": doctor_name,
            "session_id": session_id or "",
            "patient": patient_name,
        }
        if transcript:
            end_payload["transcript"] = transcript
        send_tcp(end_payload)

        try:
            want_rx = input("\n[DOCTOR PORTAL] Issue a digital prescription (Rx) for this patient? (yes/no): ").strip().lower()
            if want_rx in ("yes", "y"):
                diagnosis = input("  Primary Diagnosis: ").strip() or "General Consultation"
                meds = []
                print("  Enter prescribed medications (press Enter on Medication Name when done):")
                while True:
                    m_name = input("    Medication Name: ").strip()
                    if not m_name:
                        break
                    m_dose = input("    Dosage (e.g., 500mg): ").strip() or "Standard"
                    m_freq = input("    Frequency (e.g., Twice daily): ").strip() or "Daily"
                    m_dur = input("    Duration (e.g., 5 days): ").strip() or "5 days"
                    m_notes = input("    Notes (optional): ").strip()
                    meds.append({"name": m_name, "dosage": m_dose, "frequency": m_freq, "duration": m_dur, "notes": m_notes})
                instructions = input("  General Advice / Dietary Precautions: ").strip()
                rx_res = send_tcp({
                    "command": "ISSUE_PRESCRIPTION",
                    "token": _doctor_token,
                    "session_id": session_id or "",
                    "doctor": doctor_name,
                    "patient": patient_name,
                    "diagnosis": diagnosis,
                    "medications": meds,
                    "instructions": instructions,
                })
                if rx_res and rx_res.get("status") == "OK":
                    print(f"  [OK] Digital prescription issued successfully (Rx ID: {rx_res.get('prescription_id')})")
        except Exception as e:
            print(f"  Notice: Could not issue prescription: {e}")

        try:
            want_pdf = input("\n[DOCTOR PORTAL] Export a formatted PDF summary of this consultation? (yes/no): ").strip().lower()
            if want_pdf in ("yes", "y"):
                print("  Generating PDF transcript summary via Celery worker...")
                res = send_tcp({
                    "command": "GENERATE_TRANSCRIPT_PDF",
                    "token": _doctor_token,
                    "session_id": session_id,
                    "doctor": doctor_name,
                })
                if res and res.get("status") == "OK":
                    pdf_path = res.get("pdf_path", "data/summaries/")
                    print(f"  [OK] PDF transcript summary exported to:\n    {pdf_path}")

                else:
                    print(f"  Notice: Could not generate PDF summary: {res}")
        except Exception as e:
            print(f"  Notice: Could not complete PDF export request: {e}")



if __name__ == "__main__":
    main()
