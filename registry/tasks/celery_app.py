"""Celery application configuration.

Usage:
    celery -A registry.tasks.celery_app worker --loglevel=info
"""

from __future__ import annotations

from celery import Celery
from celery.schedules import crontab

from registry.core.config import settings

app = Celery(
    "modelionn",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
)

app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    result_expires=3600,  # 1 hour
    broker_transport_options={
        "max_retries": 1,
        "interval_start": 0,
        "interval_step": 0.2,
        "interval_max": 0.5,
        "socket_connect_timeout": 2,
        "socket_timeout": 2,
    },
    broker_connection_retry_on_startup=False,
    beat_schedule={
        "reset-daily-api-key-counters": {
            "task": "registry.tasks.periodic.reset_daily_api_key_counters",
            "schedule": crontab(minute=0, hour=0),  # midnight UTC
        },
        "refresh-prover-rankings": {
            "task": "registry.tasks.periodic.refresh_prover_rankings",
            "schedule": crontab(minute=0, hour="*/6"),  # every 6 hours
        },
        "check-prover-health": {
            "task": "registry.tasks.prover_health.check_prover_health",
            "schedule": 60.0,  # every 60 seconds
        },
        "update-prover-rankings": {
            "task": "registry.tasks.prover_health.update_prover_rankings",
            "schedule": crontab(minute="*/30"),  # every 30 minutes
        },
        "cleanup-stale-proof-jobs": {
            "task": "registry.tasks.prover_health.cleanup_stale_jobs",
            "schedule": crontab(minute="*/5"),  # every 5 minutes
        },
    },
)

# Auto-discover tasks in the tasks package
app.autodiscover_tasks(["registry.tasks"])
