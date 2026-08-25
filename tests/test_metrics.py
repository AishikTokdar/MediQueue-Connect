import os
import sys
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "server"))

from metrics import REQUESTS_TOTAL, ACTIVE_CONNECTIONS, QUEUE_DEPTH, start_metrics_server


def test_prometheus_metrics():
    # Test counter increment
    REQUESTS_TOTAL.labels(command="TEST_CMD", status="OK").inc()
    
    # Test gauge operations
    ACTIVE_CONNECTIONS.inc()
    ACTIVE_CONNECTIONS.dec()

    QUEUE_DEPTH.labels(doctor="Dr. TestDoc").set(3)

    # Test exporter server startup (port 0 or 8001)
    started = start_metrics_server(8001)
    assert started is True
