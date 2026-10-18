import os

try:
    from celery import Celery
    _CELERY_AVAILABLE = True
except ImportError:
    _CELERY_AVAILABLE = False

    class _DummyTask:
        def __init__(self, func, bind=False):
            self.func = func
            self.bind = bind

        def delay(self, *args, **kwargs):
            class _DummyResult:
                id = "local-sync"

                def ready(self):
                    return True

                @property
                def result(self):
                    return None

            return _DummyResult()

        def retry(self, *args, **kwargs):
            pass

        def __call__(self, *args, **kwargs):
            if self.bind:
                return self.func(self, *args, **kwargs)
            return self.func(*args, **kwargs)

    class Celery:
        def __init__(self, *args, **kwargs):
            self.conf = {}

        def task(self, *args, **kwargs):
            bind = kwargs.get("bind", False)
            def decorator(func):
                return _DummyTask(func, bind=bind)
            return decorator

        def start(self):
            pass


RABBITMQ_URL = os.getenv("RABBITMQ_URL", "amqp://guest:guest@127.0.0.1:5672//")
REDIS_URL = os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0")
ALWAYS_EAGER = os.getenv("CELERY_ALWAYS_EAGER", "false").lower() in ("true", "1", "yes")

celery_app = Celery(
    "mediqueue_tasks",
    broker=RABBITMQ_URL,
    backend=REDIS_URL,
    include=["server.tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_time_limit=300,
    task_always_eager=ALWAYS_EAGER,
    task_eager_propagates=True,
    beat_schedule={
        "periodic-appointment-reminder-sweep-15m": {
            "task": "server.tasks.dispatch_scheduled_reminders_task",
            "schedule": 900.0,  # Run every 15 minutes
            "args": (1,),  # Scan upcoming 24 hours
        },
    },
)

if __name__ == "__main__":
    celery_app.start()
