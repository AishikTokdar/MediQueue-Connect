import os
import sys
import time
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "server"))

from queue_manager import QueueManager, QueueEntry


def test_queue_entry_score_and_aging_bonus():
    now = 1000.0
    entry_immediate = QueueEntry(username="patient_crit", esi_level=1, arrival_time=now)
    assert entry_immediate.score(now) == 1.0

    entry_routine = QueueEntry(username="patient_rout", esi_level=5, arrival_time=now - 240.0)
    # 240 seconds waiting: age bonus = (240 / 60) * 0.25 = 1.0
    # Effective score: 5.0 - 1.0 = 4.0
    assert entry_routine.score(now) == 4.0


def test_queue_manager_esi_triage_ordering():
    qm = QueueManager()
    doc = "Dr. CardiologyExpert"

    # Enqueue a routine patient first (ESI 5)
    qm.enqueue(doc, "routine_patient", esi_level=5)
    # Enqueue an urgent patient later (ESI 2)
    qm.enqueue(doc, "urgent_patient", esi_level=2)
    # Enqueue a critical resuscitation patient last (ESI 1)
    qm.enqueue(doc, "critical_patient", esi_level=1)

    # Queue must be ordered: critical (1) -> urgent (2) -> routine (5)
    ordered = qm.get_queue(doc)
    assert ordered == ["critical_patient", "urgent_patient", "routine_patient"]


def test_queue_manager_anti_starvation_promotion():
    qm = QueueManager()
    doc = "Dr. TriageLead"
    now = time.time()

    # Patient A arrives earlier with ESI 3 (Urgent)
    entry_a = QueueEntry(username="patient_waiting", esi_level=3, arrival_time=now - 300.0)
    qm._ensure_doctor(doc)
    qm._queues[doc].append(entry_a)

    # Patient B arrives just now with ESI 2 (Emergent)
    entry_b = QueueEntry(username="patient_fresh", esi_level=2, arrival_time=now)
    qm._queues[doc].append(entry_b)

    qm._sort_and_recompute(doc)
    # Patient A has waited 300s -> bonus = (300/60)*0.25 = 1.25 -> score = 3 - 1.25 = 1.75
    # Patient B has waited 0s -> score = 2.0
    # Because 1.75 < 2.0, Patient A must be promoted ahead of Patient B!
    ordered = qm.get_queue(doc)
    assert ordered[0] == "patient_waiting"
    assert ordered[1] == "patient_fresh"


def test_queue_manager_session_lifecycle():
    qm = QueueManager()
    doc = "Dr. SessionDoc"

    assert qm.is_busy(doc) is False
    assert qm.try_start_session(doc, "patient1") is True
    assert qm.is_busy(doc) is True

    # Concurrent session start must be rejected
    assert qm.try_start_session(doc, "patient2") is False

    # Enqueue patient2 for next turn
    qm.enqueue(doc, "patient2", esi_level=3)

    # End session: must return patient2 as next in queue
    next_patient_tuple = qm.end_session(doc)
    assert next_patient_tuple is not None
    assert next_patient_tuple[0] == "patient2"
    assert qm.is_busy(doc) is True  # Auto-transitions to active patient


def test_queue_manager_cancellation():
    qm = QueueManager()
    doc = "Dr. CancelDoc"

    qm.enqueue(doc, "p1", esi_level=4)
    qm.enqueue(doc, "p2", esi_level=4)

    assert qm.get_queue(doc) == ["p1", "p2"]
    assert qm.dequeue_patient(doc, "p1") is True
    assert qm.get_queue(doc) == ["p2"]
    assert qm.dequeue_patient(doc, "non_existent") is False

