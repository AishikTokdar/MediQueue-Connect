from prometheus_client import Counter, Gauge, Histogram, start_http_server

REQUESTS_TOTAL = Counter(
    "mediqueue_requests_total",
    "Total socket RPC requests handled",
    ["command", "status"]
)

ACTIVE_CONNECTIONS = Gauge(
    "mediqueue_active_connections",
    "Current active client socket connections"
)

QUEUE_DEPTH = Gauge(
    "mediqueue_queue_depth",
    "Current waiting queue depth per doctor",
    ["doctor"]
)

REQUEST_LATENCY = Histogram(
    "mediqueue_request_duration_seconds",
    "Request latency duration in seconds",
    ["command"]
)

BOOKINGS_TOTAL = Counter(
    "mediqueue_bookings_total",
    "Total appointment bookings created"
)

_server_started = False


def start_metrics_server(port: int = 8000) -> bool:
    global _server_started
    if _server_started:
        return True
    try:
        start_http_server(port)
        _server_started = True
        return True
    except Exception as e:
        print(f"[WARN] Failed to start Prometheus metrics exporter on port {port}: {e}")
        return False
