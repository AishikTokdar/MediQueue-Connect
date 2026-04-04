import socket
import json
import sys
import os
import threading
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "server"))

from crypto_utils import (
    generate_session_key,
    encrypt_session_key,
    decrypt_session_key,
    decrypt_message,
    encrypt_message,
    crypto_available,
)

HOST = "127.0.0.1"
SERVER_PORT = 4000

_current_session_id = None


def send_tcp(payload: dict) -> dict | None:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.connect((HOST, SERVER_PORT))
        s.sendall((json.dumps(payload) + "\n").encode())
        data = b""
        while True:
            chunk = s.recv(4096)
            if not chunk:
                break
            data += chunk
            if b"\n" in data:
                break
        s.close()
        return json.loads(data.split(b"\n")[0].decode())
    except Exception as e:
        print(f"[WARN] TCP to server failed: {e}")
        return None


def main():
    if len(sys.argv) < 2:
        print("Usage: python doctor.py <doctor_name>")
        sys.exit(1)

    doctor_name = sys.argv[1]

    data_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "doctors.json")
    with open(data_path) as f:
        doctors = json.load(f)

    if doctor_name not in doctors:
        print(f"Error: Doctor '{doctor_name}' not found in doctors.json")
        sys.exit(1)

    info = doctors[doctor_name]
    udp_port = info["udp_port"]
    specialization = info.get("specialization", "General")

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((HOST, udp_port))

    print(f"\n{'='*55}")
    print(f"  Dr. {doctor_name}  –  {specialization}")
    print(f"  UDP port: {udp_port}")
    print(f"{'='*55}")
    print("  Waiting for patients...\n")

    global _current_session_id
    peers = {}

    res = send_tcp({
        "command": "DOCTOR_ONLINE",
        "token": "DOCTOR_INTERNAL",
        "doctor": doctor_name
    })
    
    if res is None:
        print("\nHealth Server stopped")
        sys.exit(1)

    def push_subscriber():
        try:
            sub = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sub.connect((HOST, SERVER_PORT))
            sub.sendall((json.dumps({"command": "SUBSCRIBE", "token": "DOCTOR_INTERNAL"}) + "\n").encode())
            data = b""
            while True:
                chunk = sub.recv(8192)
                if not chunk: break
                data += chunk
                while b"\n" in data:
                    line, data = data.split(b"\n", 1)
                    if line:
                        msg = json.loads(line.decode())
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

    try:
        while True:
            try:
                data, addr = sock.recvfrom(4096)
                msg = json.loads(data.decode())

                if msg["type"] == "HELLO":
                    if peers and _current_session_id and msg.get("session_id", "") != _current_session_id:
                        sock.sendto(json.dumps({"type": "BUSY"}).encode(), addr)
                        continue

                    patient_name = msg.get("patient", "peer")
                    _current_session_id = msg.get("session_id", "unknown")
                    
                    s_key = None
                    if crypto_available():
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

                    peers[addr] = {"name": patient_name, "session_key": s_key}
                    print(f"\n[SESSION STARTED/JOINED] {patient_name}  ID: {_current_session_id}\n")

                elif msg["type"] == "KEY_EXCHANGE":
                    enc_key = msg.get("encrypted_key")
                    s_key = decrypt_session_key(enc_key) if enc_key else None
                    peer_name = "Doctor (Invited)"
                    peers[addr] = {"name": peer_name, "session_key": s_key}
                    print(f"\n[JOINED] {peer_name}\n")
                    
                elif msg["type"] == "READY":
                    peer_name = "Doctor (Invited - Plain)"
                    peers[addr] = {"name": peer_name, "session_key": None}
                    print(f"\n[JOINED] {peer_name}\n")

                elif msg["type"] == "CHAT" and addr in peers:
                    p_info = peers[addr]
                    s_key = p_info["session_key"]
                    p_name = p_info["name"]
                    
                    ciphertext = msg["text"]
                    plaintext = decrypt_message(ciphertext, s_key) if s_key else ciphertext

                    print(f"\n[{p_name}]: {plaintext}")
                    
                    for peer_addr, peer_info in peers.items():
                        if peer_addr != addr:
                            other_key = peer_info["session_key"]
                            forward_msg = f"[{p_name}] {plaintext}"
                            f_cipher = encrypt_message(forward_msg, other_key) if other_key else forward_msg
                            sock.sendto(json.dumps({"type": "CHAT", "text": f_cipher}).encode(), peer_addr)

                    reply = input("Reply (or /invite <doc>): ").strip()

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
                        _notify_server_end(doctor_name, _current_session_id)
                        peers.clear()
                        _current_session_id = None
                        continue

                    for peer_addr, peer_info in peers.items():
                        my_cipher = encrypt_message(reply, peer_info["session_key"]) if peer_info["session_key"] else reply
                        sock.sendto(json.dumps({"type": "CHAT", "text": my_cipher}).encode(), peer_addr)

                elif msg["type"] == "EXIT" and addr in peers:
                    p_name = peers[addr]["name"]
                    print(f"\n[{p_name} LEFT SESSION]\n")
                    del peers[addr]
                    if not peers:
                        _notify_server_end(doctor_name, _current_session_id)
                        _current_session_id = None
                        print("\n[SESSION EMPTY -> ENDED]\n")

            except OSError as e:
                if hasattr(e, "winerror") and e.winerror == 10054:
                    continue  # Windows ICMP port-unreachable; safe to ignore
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


def _notify_server_end(doctor_name: str, session_id: str | None) -> None:
    if session_id:
        send_tcp({
            "command": "END_SESSION",
            "token": "DOCTOR_INTERNAL",
            "doctor": doctor_name,
            "session_id": session_id or "",
        })


if __name__ == "__main__":
    main()
