import os
import sys
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "server"))

from auth import AuthManager
from scheduler import Scheduler
from db import init_db, get_db_connection, get_audit_logs


@pytest.fixture(autouse=True)
def setup_test_db(tmp_path, monkeypatch):
    test_db = str(tmp_path / "test_mediqueue.db")
    monkeypatch.setattr("db.DB_PATH", test_db)
    init_db()


def test_auth_manager_register_and_login():
    auth = AuthManager()
    user = "test_patient_1"
    pwd = "SecurePassword123!"
    insurance = ["Aetna", "BlueCross"]

    assert auth.register(user, pwd, insurance) is True
    assert auth.register(user, pwd, insurance) is False

    assert auth.authenticate(user, pwd) is True
    assert auth.authenticate(user, "WrongPassword") is False

    token = "test_token_123"
    auth.create_session(token, user)
    assert auth.validate(token) is True
    assert auth.get_insurance(token) == insurance
    assert auth.get_user(token) == user


def test_scheduler_doctor_and_booking():
    sched = Scheduler()
    doc_name = "Dr. TestSmith"
    spec = "Cardiology"
    insurance = ["Aetna"]
    udp_port = 5005
    slots = ["9AM", "10AM"]

    reg_resp = sched.register_doctor(doc_name, spec, insurance, udp_port, slots)
    assert reg_resp["status"] == "OK"

    available = sched.get_slots(insurance, spec)
    assert doc_name in available
    assert available[doc_name]["slots"] == ["9AM", "10AM"]

    book_resp = sched.book_slot("test_patient_1", doc_name, "9AM")
    assert book_resp["status"] == "BOOKED"

    available_after = sched.get_slots(insurance, spec)
    assert "9AM" not in available_after[doc_name]["slots"]
    assert "10AM" in available_after[doc_name]["slots"]

    dup_resp = sched.book_slot("test_patient_2", doc_name, "9AM")
    assert dup_resp["status"] == "UNAVAILABLE"

    cancel_resp = sched.remove_booking_for_patient("test_patient_1", doc_name, "9AM")
    assert cancel_resp["status"] == "OK"


def test_audit_logs():
    auth = AuthManager()
    user = "audit_user"
    auth.register(user, "password", ["Aetna"])

    logs = get_audit_logs(limit=10)
    assert len(logs) > 0
    actions = [l["action"] for l in logs]
    assert "REGISTER_USER" in actions
