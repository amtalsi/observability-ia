import os
import time
import asyncio
import logging
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, BackgroundTasks
from fastapi.responses import StreamingResponse
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from pythonjsonlogger import jsonlogger

from database import init_db, save_report, get_reports
from agent import run_analysis, run_interactive
from vectorstore import init_collection, index_report

# ── Logging ───────────────────────────────────────────────────────────────────
logger = logging.getLogger("ai-agent")
handler = logging.StreamHandler()
handler.setFormatter(jsonlogger.JsonFormatter("%(asctime)s %(name)s %(levelname)s %(message)s"))
logger.addHandler(handler)
logger.setLevel(logging.INFO)

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://ollama:11434")
ANALYSIS_INTERVAL = int(os.getenv("ANALYSIS_INTERVAL_MINUTES", "15"))

scheduler = AsyncIOScheduler()


# ── Model management ───────────────────────────────────────────────────────────

async def _pull_model(name: str) -> None:
    """Pull an Ollama model if not already available."""
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(f"{OLLAMA_URL}/api/tags")
            models = [m["name"] for m in resp.json().get("models", [])]
            if any(name in m for m in models):
                logger.info(f"Model {name} already available")
                return
        logger.info(f"Pulling {name}…")
        async with httpx.AsyncClient(timeout=1800) as client:
            async with client.stream("POST", f"{OLLAMA_URL}/api/pull", json={"name": name}) as r:
                async for line in r.aiter_lines():
                    if '"status":"success"' in line:
                        logger.info(f"Model {name} pulled successfully")
                        break
    except Exception as e:
        logger.warning(f"Could not pull {name}: {e}")


async def pull_models() -> None:
    """Pull both LLM (llama3.1:8b) and embedding (nomic-embed-text) models."""
    await asyncio.sleep(10)  # let Ollama finish startup
    await _pull_model("llama3.1:8b")
    await _pull_model("nomic-embed-text")


# ── Analysis pipeline ──────────────────────────────────────────────────────────

async def _analyze_and_persist(trigger: str, alert_name: str = "", severity: str = "") -> dict:
    """Run analysis, save to PostgreSQL, index in Qdrant."""
    report = await run_analysis(trigger, alert_name, severity)
    report_id = save_report(report)
    logger.info("Report saved", extra={"report_id": report_id, "severity": report["severity"]})
    # Index in Qdrant for future RAG retrieval
    report_with_id = {**report, "created_at": str(report_id)}
    asyncio.create_task(asyncio.get_event_loop().run_in_executor(
        None, lambda: index_report(report_with_id)
    ))
    return report


async def scheduled_analysis() -> None:
    logger.info("Scheduled health analysis starting")
    await _analyze_and_persist("scheduled")


# ── Lifecycle ──────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    init_collection()
    asyncio.create_task(pull_models())
    scheduler.add_job(scheduled_analysis, "interval", minutes=ANALYSIS_INTERVAL, id="health-check")
    scheduler.start()
    logger.info("AI Agent started", extra={"interval_minutes": ANALYSIS_INTERVAL})
    yield
    scheduler.shutdown()


# ── App ────────────────────────────────────────────────────────────────────────

app = FastAPI(title="AI Observability Agent", lifespan=lifespan)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/webhook/alert")
async def alert_webhook(payload: dict, background_tasks: BackgroundTasks):
    """Receive Alertmanager webhook → trigger background AI analysis."""
    alerts = payload.get("alerts", [])
    firing = [a for a in alerts if a.get("status") == "firing"]
    for alert in firing:
        name = alert.get("labels", {}).get("alertname", "Unknown")
        sev = alert.get("labels", {}).get("severity", "unknown")
        logger.info("Alert received", extra={"alert_name": name, "severity": sev})
        background_tasks.add_task(_analyze_and_persist, "alert", name, sev)
    return {"status": "accepted", "firing_count": len(firing)}


@app.post("/analyze")
async def manual_analyze():
    """Trigger a manual health analysis (blocking)."""
    report = await _analyze_and_persist("manual")
    return report


@app.get("/reports")
def list_reports(limit: int = 20):
    return get_reports(limit)


# ── OpenAI-compatible API (for Open WebUI) ─────────────────────────────────────

@app.get("/v1/models")
def list_models():
    return {
        "object": "list",
        "data": [{
            "id": "observability-ai",
            "object": "model",
            "created": int(time.time()),
            "owned_by": "observability",
        }],
    }


@app.post("/v1/chat/completions")
async def chat_completions(payload: dict):
    """OpenAI-compatible chat endpoint wired to the observability agent."""
    messages = payload.get("messages", [])
    question = next(
        (m["content"] for m in reversed(messages) if m.get("role") == "user"),
        "Quel est l'état de santé du système ?",
    )
    stream = payload.get("stream", False)
    logger.info("Interactive query", extra={"question": question[:100]})

    answer = await run_interactive(question)
    created = int(time.time())
    cid = f"chatcmpl-{created}"

    if stream:
        async def _stream():
            # send content in one chunk then close
            chunk = {
                "id": cid, "object": "chat.completion.chunk", "created": created,
                "model": "observability-ai",
                "choices": [{"index": 0, "delta": {"role": "assistant", "content": answer}, "finish_reason": None}],
            }
            import json as _json
            yield f"data: {_json.dumps(chunk)}\n\n"
            done = {
                "id": cid, "object": "chat.completion.chunk", "created": created,
                "model": "observability-ai",
                "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
            }
            yield f"data: {_json.dumps(done)}\n\n"
            yield "data: [DONE]\n\n"
        return StreamingResponse(_stream(), media_type="text/event-stream")

    return {
        "id": cid, "object": "chat.completion", "created": created,
        "model": "observability-ai",
        "choices": [{"index": 0, "message": {"role": "assistant", "content": answer}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    }
