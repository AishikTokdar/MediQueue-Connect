import os
import sys
import socket
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "server"))

from protocol import send_framed, recv_framed


def test_framed_protocol_pack_unpack():
    # Use socketpair for in-memory socket testing
    server_sock, client_sock = socket.socketpair()

    payload = {
        "command": "LOGIN",
        "username": "test_user",
        "nested": {"key": [1, 2, 3]},
    }

    send_framed(client_sock, payload)
    received = recv_framed(server_sock)

    assert received == payload

    server_sock.close()
    client_sock.close()


def test_framed_protocol_legacy_fallback():
    server_sock, client_sock = socket.socketpair()

    # Legacy raw JSON payload ending with newline
    legacy_payload = b'{"command": "PING"}\n'
    client_sock.sendall(legacy_payload)

    received = recv_framed(server_sock)
    assert received == {"command": "PING"}

    server_sock.close()
    client_sock.close()
