"""Celery application: queues, routing, retries, dead-letter queue, beat schedule.

Queue topology:
  * ``ingest``   - connector sync + document processing (CPU/IO heavy)
  * ``embed``    - embedding generation (model-bound)
  * ``dlq``      - terminal failures parked for inspection/replay
  * ``periodic`` - scheduled maintenance (cursor-based incremental syncs, DLQ metrics)
"""

from __future__ import annotations

from celery import Celery
from celery.signals import worker_process_init
from kombu import Exchange, Queue
from platform_core.config import get_settings
from platform_core.logging import configure_logging
from platform_core.telemetry import instrument_clients, setup_telemetry

settings = get_settings()

celery_app = Celery(
    "data_platform",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=["workers.tasks"],
)

default_exchange = Exchange("data_platform", type="direct")
celery_app.conf.task_queues = (
    Queue("ingest", default_exchange, routing_key="ingest"),
    Queue("embed", default_exchange, routing_key="embed"),
    Queue("dlq", Exchange("dlq", type="direct"), routing_key="dlq"),
    Queue("periodic", default_exchange, routing_key="periodic"),
)

celery_app.conf.update(
    task_default_queue="ingest",
    task_default_exchange="data_platform",
    task_default_routing_key="ingest",
    task_routes={
        "workers.tasks.sync_connector": {"queue": "ingest"},
        "workers.tasks.process_record": {"queue": "ingest"},
        "workers.tasks.generate_embeddings": {"queue": "embed"},
        "workers.tasks.move_to_dlq": {"queue": "dlq"},
        "workers.tasks.*": {"queue": "ingest"},
    },
    # Reliability: at-least-once delivery + visibility timeout for long jobs.
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,  # fair dispatch for heterogeneous job sizes
    task_track_started=True,
    task_time_limit=1800,
    task_soft_time_limit=1500,
    result_expires=86400,
    broker_transport_options={"visibility_timeout": 3600},
    task_default_retry_delay=5,
    task_max_retries=5,
)

# Periodic incremental syncs + DLQ depth metrics.
celery_app.conf.beat_schedule = {
    "incremental-sync-active-connectors": {
        "task": "workers.tasks.scan_active_connectors",
        "schedule": 300.0,
        "options": {"queue": "periodic"},
    },
    "publish-dlq-metrics": {
        "task": "workers.tasks.publish_dlq_metrics",
        "schedule": 60.0,
        "options": {"queue": "periodic"},
    },
}


@worker_process_init.connect
def _init_worker(**_: object) -> None:
    configure_logging(service_name="worker", level=settings.log_level, json_logs=settings.log_json)
    setup_telemetry(settings)
    instrument_clients()
