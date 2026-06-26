"""OpenTelemetry tracing + Prometheus metrics bootstrap.

``setup_telemetry`` is called once per process. FastAPI/SQLAlchemy/Redis/Celery
auto-instrumentation is wired here so spans propagate across service boundaries via
W3C ``traceparent`` headers, giving end-to-end distributed traces.
"""

from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram

from .config import Settings

# ---- Application-level metrics (exposed at /metrics) ----
INGEST_JOBS_TOTAL = Counter(
    "ingest_jobs_total", "Ingestion jobs created", ["connector_type", "status"]
)
JOB_PROCESSING_SECONDS = Histogram(
    "job_processing_seconds",
    "Time spent processing an ingestion job",
    ["job_type"],
    buckets=(0.1, 0.5, 1, 2, 5, 10, 30, 60, 120, 300),
)
EMBEDDINGS_GENERATED_TOTAL = Counter(
    "embeddings_generated_total", "Embeddings generated", ["provider"]
)
SEARCH_REQUESTS_TOTAL = Counter("search_requests_total", "Context search requests", ["mode"])
CIRCUIT_BREAKER_STATE = Gauge(
    "circuit_breaker_state", "Circuit breaker state (0=closed,1=half_open,2=open)", ["name"]
)
DLQ_DEPTH = Gauge("dlq_depth", "Messages currently in the dead-letter queue", ["queue"])
CACHE_EVENTS_TOTAL = Counter("cache_events_total", "Cache hits/misses", ["result"])


def setup_telemetry(settings: Settings) -> None:
    if not settings.otel_exporter_otlp_endpoint:
        return
    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        resource = Resource.create(
            {
                "service.name": settings.service_name,
                "service.namespace": "data-platform",
                "deployment.environment": settings.environment.value,
            }
        )
        provider = TracerProvider(resource=resource)
        provider.add_span_processor(
            BatchSpanProcessor(
                OTLPSpanExporter(endpoint=settings.otel_exporter_otlp_endpoint, insecure=True)
            )
        )
        trace.set_tracer_provider(provider)
    except Exception:  # pragma: no cover - never crash a service on telemetry init
        return


def instrument_fastapi(app: object) -> None:
    try:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

        FastAPIInstrumentor.instrument_app(app)  # type: ignore[arg-type]
    except Exception:  # pragma: no cover
        pass


def instrument_clients() -> None:
    """Auto-instrument SQLAlchemy + Redis + Celery clients in this process."""
    for module, cls in (
        ("opentelemetry.instrumentation.sqlalchemy", "SQLAlchemyInstrumentor"),
        ("opentelemetry.instrumentation.redis", "RedisInstrumentor"),
        ("opentelemetry.instrumentation.celery", "CeleryInstrumentor"),
    ):
        try:
            mod = __import__(module, fromlist=[cls])
            getattr(mod, cls)().instrument()
        except Exception:  # pragma: no cover
            continue
