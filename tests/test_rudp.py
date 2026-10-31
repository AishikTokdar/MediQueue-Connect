import json
import os
import socket
import sys
import threading
import time
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "server"))

from rudp import RUDPPacket, RUDPConnection, send_reliable_message


def test_rudp_packet_valid_serialization():
    payload = {"msg": "Patient triage check", "patient": "patient1"}
    pkt = RUDPPacket(pkt_type="DATA", seq=1, ack=0, payload=payload)
    raw = pkt.to_bytes()

    restored = RUDPPacket.from_bytes(raw)
    assert restored is not None
    assert restored.pkt_type == "DATA"
    assert restored.seq == 1
    assert restored.payload == payload
    assert restored.is_valid() is True


def test_rudp_packet_corruption_detection():
    payload = {"msg": "Normal packet"}
    pkt = RUDPPacket(pkt_type="DATA", seq=5, payload=payload)
    raw = pkt.to_bytes()

    # Tamper with the raw payload bytes
    tampered_dict = json.loads(raw.decode("utf-8"))
    tampered_dict["payload"]["msg"] = "Tampered content"
    tampered_raw = json.dumps(tampered_dict).encode("utf-8")

    restored = RUDPPacket.from_bytes(tampered_raw)
    assert restored is None  # Checksum mismatch must cause rejection


def test_rudp_connection_duplicate_suppression():
    conn = RUDPConnection(peer_addr=("127.0.0.1", 9999))
    mock_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    mock_sock.bind(("127.0.0.1", 0))

    try:
        pkt = RUDPPacket(pkt_type="DATA", seq=42, payload={"text": "hello"})
        raw = pkt.to_bytes()

        # First reception: should accept payload
        payload1, is_rudp1 = conn.handle_incoming(raw, ("127.0.0.1", 9999), mock_sock)
        assert is_rudp1 is True
        assert payload1 == {"text": "hello"}

        # Duplicate reception: should reject duplicate payload (returns None, True)
        payload2, is_rudp2 = conn.handle_incoming(raw, ("127.0.0.1", 9999), mock_sock)
        assert is_rudp2 is True
        assert payload2 is None
    finally:
        mock_sock.close()


def test_rudp_reliable_send_and_ack_loop():
    # Setup sender and receiver UDP sockets on loopback
    receiver_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    receiver_sock.bind(("127.0.0.1", 0))
    recv_addr = receiver_sock.getsockname()

    sender_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sender_sock.bind(("127.0.0.1", 0))

    received_data = []

    def run_receiver():
        conn = RUDPConnection(peer_addr=sender_sock.getsockname(), rto=0.2)
        receiver_sock.settimeout(1.0)
        try:
            raw, addr = receiver_sock.recvfrom(4096)
            data, is_rudp = conn.handle_incoming(raw, addr, receiver_sock)
            if data:
                received_data.append(data)
        except Exception:
            pass

    t = threading.Thread(target=run_receiver)
    t.start()

    payload = {"command": "CONSULT_NOTE", "detail": "Vital signs stable"}
    sender_conn = RUDPConnection(peer_addr=recv_addr, rto=0.3, max_retries=3)
    delivered = sender_conn.send_reliable(sender_sock, payload)

    t.join(timeout=2.0)
    sender_sock.close()
    receiver_sock.close()

    assert delivered is True
    assert len(received_data) == 1
    assert received_data[0] == payload

