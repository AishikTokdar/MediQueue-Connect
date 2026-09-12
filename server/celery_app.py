import os
from celery import Celery

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
)

if __name__ == "__main__":
    celery_app.start()
