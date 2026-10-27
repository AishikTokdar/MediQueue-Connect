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
    test_db = str(tmp_path / "rbac_test.db")
    monkeypatch.setattr("db.DB_PATH", test_db)
    init_db()


def test_doctor_rbac_and_bypass_rejection():
    asyncio.run(_test_doctor_rbac_and_bypass_rejection())


async def _test_doctor_rbac_and_bypass_rejection():
    server = await asyncio.start_server(handle_client, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]

    reader, writer = await asyncio.open_connection("127.0.0.1", port)

    try:
        # 1. Attempt backdoor bypass token: DOCTOR_INTERNAL -> MUST BE REJECTED
        await async_send_framed(writer, {
            "command": "ISSUE_PRESCRIPTION",
            "token": "DOCTOR_INTERNAL",
            "session_id": "fake_session",
            "doctor": "Dr. Test",
            "patient": "patient1",
            "diagnosis": "Bypass Test",
            "medications": [],
        })
        resp = await async_recv_framed(reader)
        assert resp["status"] == "ERROR"
        assert "Unauthorized" in resp["reason"]

        # 2. Register and authenticate as a normal patient
        await async_send_framed(writer, {
            "command": "REGISTER",
            "username": "charlie_patient",
            "password": "Password123!",
            "insurance": ["Aetna"]
        })
        reg_resp = await async_recv_framed(reader)
        patient_token = reg_resp["token"]

        # 3. Patient attempts to access doctor-only endpoints -> MUST BE REJECTED
        await async_send_framed(writer, {
            "command": "GET_PATIENT_INTAKE",
            "token": patient_token,
            "patient": "charlie_patient",
        })
        intake_resp = await async_recv_framed(reader)
        assert intake_resp["status"] == "ERROR"
        assert "Unauthorized" in intake_resp["reason"]

        # 4. Doctor registers and logs in with proper credentials
        await async_send_framed(writer, {
            "command": "REGISTER_DOCTOR",
            "doctor": "Dr. ValidRole",
            "specialization": "Pediatrics",
            "accepted_insurance": ["Aetna"],
            "udp_port": 5022,
            "slots": ["10AM"]
        })
        await async_recv_framed(reader)

        # Authenticate doctor
        await async_send_framed(writer, {
            "command": "DOCTOR_LOGIN",
            "doctor": "Dr. ValidRole",
            "password": "Dr. ValidRole123"
        })
        doc_login_resp = await async_recv_framed(reader)
        assert doc_login_resp["status"] == "OK"
        doc_token = doc_login_resp["token"]
        assert doc_token is not None
        assert doc_token != "DOCTOR_INTERNAL"

        # 5. Genuine doctor issues prescription -> MUST SUCCEED
        await async_send_framed(writer, {
            "command": "ISSUE_PRESCRIPTION",
            "token": doc_token,
            "session_id": "valid_session_123",
            "doctor": "Dr. ValidRole",
            "patient": "charlie_patient",
            "diagnosis": "Seasonal Allergies",
            "medications": [{"name": "Cetirizine", "dosage": "10mg", "frequency": "Daily", "duration": "7 days"}],
            "instructions": "Avoid known allergens"
        })
        rx_resp = await async_recv_framed(reader)
        assert rx_resp["status"] == "OK"
        assert "prescription_id" in rx_resp
    finally:
        writer.close()
        await writer.wait_closed()
        server.close()
        await server.wait_closed()
