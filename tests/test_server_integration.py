import asyncio
import os
import sys
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "server"))

from health_server import handle_client
from protocol import async_send_framed, async_recv_framed
from db import init_db


@pytest.fixture(autouse=True)
def setup_test_env(tmp_path, monkeypatch):
    test_db = str(tmp_path / "integration_test.db")
    monkeypatch.setattr("db.DB_PATH", test_db)
    init_db()


@pytest.mark.asyncio
async def test_full_server_async_request_flow():
    server = await asyncio.start_server(handle_client, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]

    async def client_session():
        reader, writer = await asyncio.open_connection("127.0.0.1", port)

        # 1. Register User
        await async_send_framed(writer, {
            "command": "REGISTER",
            "username": "async_patient",
            "password": "Password123!",
            "insurance": ["Aetna"]
        })
        reg_resp = await async_recv_framed(reader)
        assert reg_resp["status"] == "OK"

        # 2. Login User
        await async_send_framed(writer, {
            "command": "LOGIN",
            "username": "async_patient",
            "password": "Password123!"
        })
        login_resp = await async_recv_framed(reader)
        assert login_resp["status"] == "OK"
        token = login_resp["token"]
        assert token is not None

        # 3. Register Doctor
        await async_send_framed(writer, {
            "command": "REGISTER_DOCTOR",
            "doctor": "Dr. AsyncDoc",
            "specialization": "Neurology",
            "accepted_insurance": ["Aetna"],
            "udp_port": 5010,
            "slots": ["11AM"]
        })
        doc_resp = await async_recv_framed(reader)
        assert doc_resp["status"] == "OK"

        # 4. Get Available Slots
        await async_send_framed(writer, {
            "command": "GET_SLOTS",
            "token": token,
            "specialization": "Neurology"
        })
        slots_resp = await async_recv_framed(reader)
        assert slots_resp["status"] == "OK"
        assert "Dr. AsyncDoc" in slots_resp["doctors"]

        # 5. Book Slot
        await async_send_framed(writer, {
            "command": "BOOK",
            "token": token,
            "doctor": "Dr. AsyncDoc",
            "slot": "11AM"
        })
        book_resp = await async_recv_framed(reader)
        assert book_resp["status"] == "BOOKED"

        writer.close()
        await writer.wait_closed()

    await client_session()
    server.close()
    await server.wait_closed()
