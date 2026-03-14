import os
import time
import logging

from pythonjsonlogger import jsonlogger
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from prometheus_client import start_http_server, Counter, Gauge

# ── Prometheus metrics ─────────────────────────────────────────────────────────
METRICS_PORT = int(os.getenv("METRICS_PORT", "9091"))
tasks_processed = Counter("worker_tasks_processed_total", "Total tasks processed by the worker")
tasks_errors = Counter("worker_tasks_errors_total", "Total processing errors")
worker_up = Gauge("worker_up", "Worker process is alive (1=yes)")

# --- OpenTelemetry setup ---
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.resources import Resource
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter

# ── Logging ───────────────────────────────────────────────────────────────────
logger = logging.getLogger("worker")
handler = logging.StreamHandler()
handler.setFormatter(jsonlogger.JsonFormatter("%(asctime)s %(name)s %(levelname)s %(message)s"))
logger.addHandler(handler)
logger.setLevel(logging.INFO)

# ── OTel Tracing ──────────────────────────────────────────────────────────────
OTEL_ENDPOINT = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://otel-collector:4317")
SERVICE_NAME = os.getenv("OTEL_SERVICE_NAME", "worker")

resource = Resource.create({"service.name": SERVICE_NAME})
provider = TracerProvider(resource=resource)
provider.add_span_processor(
    BatchSpanProcessor(OTLPSpanExporter(endpoint=OTEL_ENDPOINT, insecure=True))
)
trace.set_tracer_provider(provider)
tracer = trace.get_tracer(__name__)

# ── DB ────────────────────────────────────────────────────────────────────────
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://user:password@postgres:5432/appdb")
POLL_INTERVAL = int(os.getenv("POLL_INTERVAL", "5"))

engine = create_engine(DATABASE_URL)
Session = sessionmaker(bind=engine)


def process_pending_tasks() -> int:
    """Pick up to 5 pending tasks, process them and mark as done. Returns count processed."""
    with Session() as db:
        rows = db.execute(
            text("SELECT id, title FROM tasks WHERE status = 'pending' ORDER BY id LIMIT 5")
        ).fetchall()

        for row in rows:
            with tracer.start_as_current_span("process_task") as span:
                span.set_attribute("task.id", row.id)
                span.set_attribute("task.title", row.title)

                logger.info("Processing task", extra={"task_id": row.id, "title": row.title})

                db.execute(
                    text("UPDATE tasks SET status = 'processing', updated_at = NOW() WHERE id = :id"),
                    {"id": row.id},
                )
                db.commit()

                time.sleep(2)  # simulate work

                db.execute(
                    text("UPDATE tasks SET status = 'done', updated_at = NOW() WHERE id = :id"),
                    {"id": row.id},
                )
                db.commit()

                logger.info("Task done", extra={"task_id": row.id})
                tasks_processed.inc()

        return len(rows)


def main():
    start_http_server(METRICS_PORT)
    worker_up.set(1)
    logger.info("Worker started", extra={"poll_interval": POLL_INTERVAL, "metrics_port": METRICS_PORT})
    while True:
        try:
            count = process_pending_tasks()
            if count:
                logger.info("Cycle complete", extra={"processed": count})
        except Exception as exc:
            logger.error("Worker error", extra={"error": str(exc)})
            tasks_errors.inc()
        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()
