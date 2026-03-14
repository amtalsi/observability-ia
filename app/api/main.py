import os
import logging
from typing import Optional, List

from fastapi import FastAPI, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from pythonjsonlogger import jsonlogger

# --- OpenTelemetry setup ---
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.resources import Resource
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor

# --- Prometheus metrics ---
from prometheus_fastapi_instrumentator import Instrumentator

from database import engine, get_db
from models import Base, Task

# ── Logging (JSON structuré) ──────────────────────────────────────────────────
logger = logging.getLogger("api")
handler = logging.StreamHandler()
handler.setFormatter(jsonlogger.JsonFormatter("%(asctime)s %(name)s %(levelname)s %(message)s"))
logger.addHandler(handler)
logger.setLevel(logging.INFO)

# ── OTel Tracing ──────────────────────────────────────────────────────────────
OTEL_ENDPOINT = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://otel-collector:4317")
SERVICE_NAME = os.getenv("OTEL_SERVICE_NAME", "api")

resource = Resource.create({"service.name": SERVICE_NAME})
provider = TracerProvider(resource=resource)
provider.add_span_processor(
    BatchSpanProcessor(OTLPSpanExporter(endpoint=OTEL_ENDPOINT, insecure=True))
)
trace.set_tracer_provider(provider)
tracer = trace.get_tracer(__name__)

# ── DB tables ─────────────────────────────────────────────────────────────────
Base.metadata.create_all(bind=engine)

# ── App ───────────────────────────────────────────────────────────────────────
app = FastAPI(title="Task Manager API")

FastAPIInstrumentor.instrument_app(app)
SQLAlchemyInstrumentor().instrument(engine=engine)
Instrumentator().instrument(app).expose(app)  # expose /metrics


# ── Schemas ───────────────────────────────────────────────────────────────────
class TaskCreate(BaseModel):
    title: str
    description: Optional[str] = None


class TaskResponse(BaseModel):
    id: int
    title: str
    description: Optional[str]
    status: str

    class Config:
        from_attributes = True


# ── Routes ────────────────────────────────────────────────────────────────────
@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/tasks", response_model=TaskResponse, status_code=201)
def create_task(payload: TaskCreate, db: Session = Depends(get_db)):
    with tracer.start_as_current_span("create_task") as span:
        task = Task(title=payload.title, description=payload.description)
        db.add(task)
        db.commit()
        db.refresh(task)
        span.set_attribute("task.id", task.id)
        logger.info("Task created", extra={"task_id": task.id, "title": task.title})
        return task


@app.get("/tasks", response_model=List[TaskResponse])
def list_tasks(db: Session = Depends(get_db)):
    return db.query(Task).all()


@app.get("/tasks/{task_id}", response_model=TaskResponse)
def get_task(task_id: int, db: Session = Depends(get_db)):
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


@app.delete("/tasks/{task_id}", status_code=204)
def delete_task(task_id: int, db: Session = Depends(get_db)):
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    db.delete(task)
    db.commit()
    logger.info("Task deleted", extra={"task_id": task_id})
