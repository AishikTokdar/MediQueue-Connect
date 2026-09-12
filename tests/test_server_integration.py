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

        # 5. Book Slot using client command alias
        await async_send_framed(writer, {
            "command": "BOOK_SLOT",
            "token": token,
            "doctor": "Dr. AsyncDoc",
            "slot": "11AM"
        })
        book_resp = await async_recv_framed(reader)
        assert book_resp["status"] == "BOOKED"

        # 6. Get Appointments using client command alias
        await async_send_framed(writer, {
            "command": "GET_MY_APPOINTMENTS",
            "token": token
        })
        appts_resp = await async_recv_framed(reader)
        assert appts_resp["status"] == "OK"
        assert len(appts_resp["appointments"]) == 1

        # 7. Doctor online notification
        await async_send_framed(writer, {
            "command": "DOCTOR_ONLINE",
            "doctor": "Dr. AsyncDoc"
        })
        doc_on_resp = await async_recv_framed(reader)
        assert doc_on_resp["status"] == "OK"

        # 8. Get Doctors for Chat
        await async_send_framed(writer, {
            "command": "GET_DOCTORS",
            "token": token,
            "specialization": "Neurology"
        })
        docs_resp = await async_recv_framed(reader)
        assert docs_resp["status"] == "OK"
        assert "Dr. AsyncDoc" in docs_resp["doctors"]
        assert docs_resp["doctors"]["Dr. AsyncDoc"]["online"] is True

        # 9. Request Chat Session
        await async_send_framed(writer, {
            "command": "REQUEST_CHAT",
            "token": token,
            "doctor": "Dr. AsyncDoc",
            "session_id": "test-session-123"
        })
        req_chat_resp = await async_recv_framed(reader)
        assert req_chat_resp["status"] in ("READY", "TURN_READY")
        assert req_chat_resp["udp_port"] == 5010

        # 10. Admin commands check
        await async_send_framed(writer, {
            "command": "ADMIN_GET_BOOKINGS"
        })
        admin_bk_resp = await async_recv_framed(reader)
        assert admin_bk_resp["status"] == "OK"
        assert "Dr. AsyncDoc" in admin_bk_resp["bookings"]

        # 11. Dashboard Stats check
        await async_send_framed(writer, {
            "command": "GET_STATS"
        })
        stats_resp = await async_recv_framed(reader)
        assert stats_resp["status"] == "OK"
        assert "queue_state" in stats_resp
        assert "uptime" in stats_resp["stats"]

        # 12. Cancel Appointment using client command alias
        await async_send_framed(writer, {
            "command": "CANCEL_MY_BOOKING",
            "token": token,
            "doctor": "Dr. AsyncDoc",
            "slot": "11AM"
        })
        cancel_resp = await async_recv_framed(reader)
        assert cancel_resp["status"] == "OK"

        writer.close()
        await writer.wait_closed()

    await client_session()
    server.close()
    await server.wait_closed()

