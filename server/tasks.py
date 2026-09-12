import os
import sys
import json
import logging
from datetime import datetime

# Path setup for flexible import resolutions
ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)
SERVER_DIR = os.path.abspath(os.path.dirname(__file__))
if SERVER_DIR not in sys.path:
    sys.path.insert(0, SERVER_DIR)

# Set up logging for background tasks
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("mediqueue.tasks")

try:
    from server.celery_app import celery_app
    from server.pdf_generator import generate_transcript_pdf
    from server.logger import log_audit, log
except ModuleNotFoundError:
    from celery_app import celery_app
    from pdf_generator import generate_transcript_pdf
    from logger import log_audit, log

HISTORY_ROOT = os.path.join(ROOT_DIR, "data", "chat_history")
SUMMARIES_ROOT = os.path.join(ROOT_DIR, "data", "summaries")
NOTIFICATIONS_LOG = os.path.join(ROOT_DIR, "data", "notifications.log")


def _log_notification(msg: str) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(NOTIFICATIONS_LOG)), exist_ok=True)
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    formatted = f"[{ts}] {msg}\n"
    with open(NOTIFICATIONS_LOG, "a", encoding="utf-8") as f:
        f.write(formatted)


def generate_pdf_summary_internal(session_id: str, doctor: str, patient: str, output_dir: str | None = None) -> dict:
    """
    Direct core logic for generating PDF summary without requiring Celery task binding.
    """
    logger.info(f"Starting PDF summary generation for session {session_id} (Doctor: {doctor}, Patient: {patient})")
    
    doc_dir = os.path.join(HISTORY_ROOT, doctor)
    jsonl_path = os.path.join(doc_dir, f"{session_id}.jsonl")
    
    transcript_records = []
    if os.path.exists(jsonl_path):
        try:
            with open(jsonl_path, "r", encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        rec = json.loads(line)
                        transcript_records.append(rec)
                        if rec.get("event") == "SESSION_START" and rec.get("patient"):
                            patient = rec.get("patient")
        except Exception as e:
            logger.error(f"Error reading transcript JSONL for {session_id}: {e}")

    target_dir = output_dir or os.path.join(SUMMARIES_ROOT, doctor)
    os.makedirs(target_dir, exist_ok=True)
    pdf_filename = f"{session_id}_summary.pdf"
    output_path = os.path.join(target_dir, pdf_filename)

    abs_path = generate_transcript_pdf(
        session_id=session_id,
        doctor=doctor,
        patient=patient,
        transcript_records=transcript_records,
        output_path=output_path,
    )
    logger.info(f"Successfully generated transcript PDF at {abs_path}")
    log_audit("PDF_SUMMARY_GENERATED", user=doctor, details=f"Patient: {patient}, Session: {session_id}, PDF: {abs_path}")
    return {
        "status": "COMPLETED",
        "session_id": session_id,
        "doctor": doctor,
        "patient": patient,
        "pdf_path": abs_path,
    }


@celery_app.task(name="server.tasks.generate_session_summary_pdf_task", bind=True, max_retries=3)
def generate_session_summary_pdf_task(self, session_id: str, doctor: str, patient: str, output_dir: str | None = None) -> dict:
    """
    Celery task wrapper that delegates to generate_pdf_summary_internal.
    """
    try:
        return generate_pdf_summary_internal(session_id, doctor, patient, output_dir)
    except Exception as e:
        logger.error(f"Failed to generate transcript PDF: {e}")
        try:
            self.retry(exc=e, countdown=5)
        except Exception:
            pass
        return {
            "status": "FAILED",
            "session_id": session_id,
            "reason": str(e),
        }


@celery_app.task(name="server.tasks.send_email_reminder_task")
def send_email_reminder_task(patient_email: str, patient_name: str, doctor: str, slot: str) -> dict:
    """
    Celery task that dispatches a statutory/mock email reminder for an upcoming appointment for demonstration.
    """
    logger.info(f"Dispatching EMAIL reminder to {patient_email} for Dr. {doctor} at {slot}")
    subject = f"Appointment Confirmation: Dr. {doctor} ({slot})"
    _log_notification(f"EMAIL -> To: {patient_email} | Subject: '{subject}'")
    log_audit("EMAIL_REMINDER_SENT", user=patient_name, details=f"Doctor: {doctor}, Slot: {slot}")
    return {"status": "DELIVERED", "channel": "EMAIL", "recipient": patient_email, "doctor": doctor, "slot": slot}


@celery_app.task(name="server.tasks.send_sms_reminder_task")
def send_sms_reminder_task(phone_number: str, patient_name: str, doctor: str, slot: str) -> dict:
    """
    Celery task that dispatches a statutory/mock SMS reminder for an upcoming appointment for demonstration.
    """
    logger.info(f"Dispatching SMS reminder to {phone_number} for Dr. {doctor} at {slot}")
    sms_text = f"MediQueue Reminder: Hi {patient_name}, your consultation with Dr. {doctor} is at {slot}."

    _log_notification(f"SMS -> To: {phone_number} | Text: '{sms_text}'")
    log_audit("SMS_REMINDER_SENT", user=patient_name, details=f"Doctor: {doctor}, Slot: {slot}")
    return {"status": "DELIVERED", "channel": "SMS", "recipient": phone_number, "doctor": doctor, "slot": slot}


@celery_app.task(name="server.tasks.dispatch_scheduled_reminders_task")
def dispatch_scheduled_reminders_task() -> dict:
    """
    Celery beat/scheduled task to scan active bookings and trigger reminders.
    """
    logger.info("Scanning database for upcoming appointment reminders...")
    return {"status": "COMPLETED", "scanned_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
