try:
    from prometheus_client import Counter, Gauge, Histogram, start_http_server
    _PROM_AVAILABLE = True
except ImportError:
    _PROM_AVAILABLE = False

    class _DummyMetric:
        def __init__(self, *args, **kwargs):
            pass

        def labels(self, *args, **kwargs):
            return self

        def inc(self, *args, **kwargs):
            pass

        def dec(self, *args, **kwargs):
            pass

        def set(self, *args, **kwargs):
            pass

        def observe(self, *args, **kwargs):
            pass

        def time(self):
            import contextlib
            return contextlib.nullcontext()

    Counter = Gauge = Histogram = _DummyMetric

    def start_http_server(port):
        pass

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

CELERY_TASKS_TOTAL = Counter(
    "mediqueue_celery_tasks_total",
    "Total background Celery tasks dispatched",
    ["task_name", "status"]
)

CELERY_TASK_DURATION = Histogram(
    "mediqueue_celery_task_duration_seconds",
    "Celery task execution duration in seconds",
    ["task_name"]
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
