import os
import json
import tempfile
import pytest
from server.pdf_generator import generate_transcript_pdf
from server.tasks import (
    generate_session_summary_pdf_task,
    send_email_reminder_task,
    send_sms_reminder_task,
    dispatch_scheduled_reminders_task,
)


def test_pdf_generator_directly():
    with tempfile.TemporaryDirectory() as tmpdir:
        output_pdf = os.path.join(tmpdir, "test_summary.pdf")
        sample_records = [
            {"event": "SESSION_START", "doctor": "doctor1", "patient": "patient1", "ts": "2026-09-12 10:00:00.000"},
            {"sender": "patient1", "text": "Hello Doctor, I have a mild fever.", "ts": "2026-09-12 10:01:05.123"},
            {"sender": "doctor1", "text": "Hi patient1, how long have you had the fever?", "ts": "2026-09-12 10:01:30.456"},
            {"sender": "patient1", "text": "Since yesterday morning.", "ts": "2026-09-12 10:02:00.789"},
            {"sender": "doctor1", "text": "I will prescribe rest and hydration.", "ts": "2026-09-12 10:03:00.000"},
            {"event": "SESSION_END", "reason": "NORMAL", "ts": "2026-09-12 10:05:00.000"},
        ]
        
        path = generate_transcript_pdf("test_session_123", "doctor1", "patient1", sample_records, output_pdf)
        assert os.path.exists(path)
        assert os.path.getsize(path) > 1000  # Non-trivial PDF file size


def test_generate_session_summary_pdf_task():
    session_id = "test_celery_session_456"
    doctor = "doctor1"
    patient = "patient1"
    
    # Write a dummy transcript JSONL
    history_dir = os.path.join(os.path.dirname(__file__), "..", "data", "chat_history", doctor)
    os.makedirs(history_dir, exist_ok=True)
    jsonl_path = os.path.join(history_dir, f"{session_id}.jsonl")
    
    with open(jsonl_path, "w", encoding="utf-8") as f:
        f.write(json.dumps({"event": "SESSION_START", "doctor": doctor, "patient": patient, "ts": "2026-09-12 10:00:00"}) + "\n")
        f.write(json.dumps({"sender": patient, "text": "Test consultation query.", "ts": "2026-09-12 10:01:00"}) + "\n")
        f.write(json.dumps({"sender": doctor, "text": "Test consultation recommendation.", "ts": "2026-09-12 10:02:00"}) + "\n")
        f.write(json.dumps({"event": "SESSION_END", "reason": "NORMAL", "ts": "2026-09-12 10:03:00"}) + "\n")

    try:
        res = generate_session_summary_pdf_task(session_id, doctor, patient)
        assert res["status"] == "COMPLETED"
        assert "pdf_path" in res
        assert os.path.exists(res["pdf_path"])
    finally:
        if os.path.exists(jsonl_path):
            os.remove(jsonl_path)


def test_email_and_sms_reminder_tasks():
    email_res = send_email_reminder_task("patient1@mediqueue.org", "patient1", "doctor1", "10AM")
    assert email_res["status"] == "DELIVERED"
    assert email_res["channel"] == "EMAIL"
    
    sms_res = send_sms_reminder_task("+15550192834", "patient1", "doctor1", "10AM")
    assert sms_res["status"] == "DELIVERED"
    assert sms_res["channel"] == "SMS"
    
    sched_res = dispatch_scheduled_reminders_task()
    assert sched_res["status"] == "COMPLETED"
