"""
LangChain agent with native tool calling (bind_tools loop).
Compatible with langchain >= 0.3 / langchain-ollama >= 0.2.
"""
import os
import time
import json
import re
import httpx
import logging
import asyncio

from langchain_ollama import ChatOllama
from langchain_core.tools import tool
from langchain_core.messages import SystemMessage, HumanMessage, ToolMessage

from vectorstore import search_similar_incidents, index_logs

logger = logging.getLogger("ai-agent.agent")

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://ollama:11434")
PROMETHEUS_URL = os.getenv("PROMETHEUS_URL", "http://prometheus:9090")
LOKI_URL = os.getenv("LOKI_URL", "http://loki:3100")
ALERTMANAGER_URL = os.getenv("ALERTMANAGER_URL", "http://alertmanager:9093")

MAX_ITERATIONS = 6


# ── Tools ──────────────────────────────────────────────────────────────────────

@tool
def query_prometheus(promql: str) -> str:
    """Query Prometheus with PromQL. Use to check: service health (up),
    HTTP error rates (rate(http_requests_total[5m])), latency, pg_up."""
    try:
        resp = httpx.get(
            f"{PROMETHEUS_URL}/api/v1/query",
            params={"query": promql},
            timeout=10,
        )
        data = resp.json()
        if data["status"] == "success":
            results = data["data"]["result"]
            return json.dumps(results[:15], ensure_ascii=False) if results else f"No data for: {promql}"
        return f"Prometheus error: {data}"
    except Exception as e:
        return f"Error: {e}"


@tool
def query_loki(logql: str, limit: int = 20) -> str:
    """Query Loki for recent logs using LogQL.
    Example: '{container=~".*api.*"} |= "error"'"""
    try:
        params = {
            "query": logql,
            "limit": str(limit),
            "start": str(int((time.time() - 900) * 1e9)),
            "end": str(int(time.time() * 1e9)),
            "direction": "backward",
        }
        resp = httpx.get(f"{LOKI_URL}/loki/api/v1/query_range", params=params, timeout=10)
        data = resp.json()
        streams = data.get("data", {}).get("result", [])
        lines = [line[:300] for stream in streams for _, line in stream.get("values", [])]
        result = "\n".join(lines[:limit]) if lines else "No logs found"
        service = re.search(r'"([^"]*)"', logql)
        index_logs(result, service.group(1) if service else "unknown")
        return result
    except Exception as e:
        return f"Error: {e}"


@tool
def get_active_alerts() -> str:
    """Get currently firing alerts from Alertmanager."""
    try:
        resp = httpx.get(f"{ALERTMANAGER_URL}/api/v2/alerts", timeout=10)
        alerts = resp.json()
        return json.dumps(alerts[:10], ensure_ascii=False, indent=2) if alerts else "Aucune alerte active"
    except Exception as e:
        return f"Error: {e}"


_TOOLS = [query_prometheus, query_loki, get_active_alerts]
_TOOLS_MAP = {t.name: t for t in _TOOLS}

SYSTEM_PROMPT = """Tu es un expert SRE spécialisé en observabilité système.

Outils disponibles :
- query_prometheus : métriques PromQL
- query_loki : logs LogQL (ex: '{{container=~".*api.*"}} |= "error"')
- get_active_alerts : alertes Alertmanager actives

Labels Prometheus exacts (IMPORTANT) :
- http_requests_total : labels job, handler, method, status ("2xx"/"4xx"/"5xx")
  Erreurs 4xx : rate(http_requests_total{{status="4xx",job="api"}}[5m])
  Erreurs 5xx : rate(http_requests_total{{status="5xx",job="api"}}[5m])
- up{{job="api"}}, up{{job="worker"}}, up{{job="postgres-exporter"}}
- pg_up, worker_tasks_processed_total, worker_tasks_errors_total

{rag_block}
Après investigation, réponds UNIQUEMENT avec un JSON valide (sans markdown) :
{{
  "summary": "résumé clair en 1 phrase",
  "analysis": "analyse détaillée avec les valeurs trouvées",
  "recommendations": "actions correctives priorisées",
  "severity": "ok"
}}
Valeurs valides pour severity : ok, warning, critical."""

INTERACTIVE_SYSTEM_PROMPT = """Tu es un assistant SRE expert en observabilité, connecté en temps réel à :
- **Prometheus** : métriques des services
- **Loki** : logs des conteneurs Docker
- **Alertmanager** : alertes actuellement actives

Outils disponibles :
- query_prometheus(promql) : interroge Prometheus avec une requête PromQL
- query_loki(logql, limit) : interroge Loki avec une requête LogQL
- get_active_alerts() : liste les alertes Alertmanager en cours

## Schéma des métriques Prometheus (IMPORTANT — utilise ces labels exacts)

**http_requests_total** — labels: handler, method, status, job, instance
  - `status` est une CLASSE : "2xx", "4xx", "5xx" (jamais un code exact comme 200 ou 404)
  - Exemples corrects :
    - Taux erreurs 4xx : rate(http_requests_total{{status="4xx",job="api"}}[5m])
    - Taux erreurs 5xx : rate(http_requests_total{{status="5xx",job="api"}}[5m])
    - Total requêtes : rate(http_requests_total{{job="api"}}[5m])

**up** — labels: job, instance
  - Services surveillés : "api", "postgres-exporter", "worker", "node-exporter"
  - Exemple : up{{job="api"}}

**worker_tasks_processed_total** / **worker_tasks_errors_total** — compteurs du worker
**worker_up** — gauge 1/0 du worker

**pg_up** — santé PostgreSQL via postgres-exporter

**http_request_duration_seconds_bucket** — latence (histogram), labels: handler, method, le, status

{rag_block}
Utilise les outils pour répondre précisément. Réponds en français, de façon claire et structurée (markdown autorisé).
Ne génère PAS de JSON brut dans ta réponse — appelle les outils directement, puis donne une réponse lisible."""


def _extract_text_tool_call(content: str) -> dict | None:
    """
    Fallback: llama3.1:8b sometimes outputs a tool call as plain JSON text
    instead of using the structured tool_calls channel.
    Detect and parse it so the loop can execute it.
    """
    if not content:
        return None
    # Try whole content as JSON first, then search for embedded JSON
    candidates = [content.strip()]
    m = re.search(r'\{[^{}]*"name"\s*:\s*"[^"]+?"[^{}]*\}', content, re.DOTALL)
    if m:
        candidates.append(m.group())
    for candidate in candidates:
        try:
            data = json.loads(candidate)
            if isinstance(data, dict) and "name" in data and data["name"] in _TOOLS_MAP:
                args = data.get("parameters") or data.get("arguments") or data.get("args") or {}
                return {"name": data["name"], "args": args, "id": f"fallback_{int(time.time())}"}
        except (json.JSONDecodeError, ValueError):
            continue
    return None


def _invoke_agent(question: str, rag_context: str, interactive: bool = False) -> str:
    """Run the tool-calling loop synchronously."""
    rag_block = (
        "CONTEXTE HISTORIQUE (incidents similaires passés) :\n" + rag_context + "\n"
        if rag_context else ""
    )
    llm = ChatOllama(model="llama3.1:8b", base_url=OLLAMA_URL, temperature=0)
    llm_with_tools = llm.bind_tools(_TOOLS)

    prompt = INTERACTIVE_SYSTEM_PROMPT if interactive else SYSTEM_PROMPT
    messages = [
        SystemMessage(content=prompt.format(rag_block=rag_block)),
        HumanMessage(content=question),
    ]

    for iteration in range(MAX_ITERATIONS):
        response = llm_with_tools.invoke(messages)
        messages.append(response)

        tool_calls = getattr(response, "tool_calls", None) or []

        # Fallback: model wrote the tool call as plain JSON text
        if not tool_calls:
            fallback = _extract_text_tool_call(response.content or "")
            if fallback:
                logger.info(f"Fallback tool call detected in content: {fallback['name']}")
                tool_calls = [fallback]
            else:
                logger.info(f"Agent finished after {iteration + 1} iterations")
                break

        for tc in tool_calls:
            name = tc["name"]
            args = tc.get("args", {})
            logger.info(f"Tool call: {name}({args})")
            try:
                result = _TOOLS_MAP[name].invoke(args)
            except Exception as e:
                result = f"Tool error: {e}"
            messages.append(ToolMessage(content=str(result), tool_call_id=tc["id"]))

    return messages[-1].content if messages else ""


def _parse_report(output: str) -> dict:
    match = re.search(r'\{[^{}]*"summary"[^{}]*\}', output, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass
    return {
        "summary": output[:200] if output else "Analyse non structurée",
        "analysis": output,
        "recommendations": "Voir l'analyse ci-dessus",
        "severity": "ok",
    }


async def run_analysis(trigger: str, alert_name: str = "", alert_severity: str = "") -> dict:
    start = time.time()

    question = (
        f"Alerte déclenchée : '{alert_name}' (sévérité : {alert_severity}). "
        "Investigue les métriques et logs pour identifier la cause racine."
        if trigger == "alert" and alert_name
        else (
            "Analyse de santé planifiée. Vérifie : "
            "1) Services up/down (up) "
            "2) Taux d'erreurs HTTP de l'API "
            "3) Santé PostgreSQL (pg_up) "
            "4) Logs d'erreurs récents."
        )
    )

    # RAG: retrieve similar past incidents
    rag_context = ""
    try:
        rag_context = await asyncio.get_event_loop().run_in_executor(
            None, lambda: search_similar_incidents(question, k=3)
        )
        if rag_context:
            logger.info("RAG context injected from Qdrant")
    except Exception as e:
        logger.warning(f"RAG retrieval failed: {e}")

    # Agent loop (runs in thread to avoid blocking event loop)
    try:
        output = await asyncio.get_event_loop().run_in_executor(
            None, lambda: _invoke_agent(question, rag_context)
        )
        report = _parse_report(output)
    except Exception as e:
        logger.error(f"Agent failed: {e}")
        report = {
            "summary": f"Erreur d'analyse: {str(e)[:150]}",
            "analysis": str(e),
            "recommendations": "Vérifier la connectivité Ollama",
            "severity": "warning",
        }

    return {
        "trigger_type": trigger,
        "alert_name": alert_name or "health-check",
        "severity": report.get("severity", "ok"),
        "summary": report.get("summary", ""),
        "analysis": report.get("analysis", ""),
        "recommendations": report.get("recommendations", ""),
        "duration_seconds": round(time.time() - start, 1),
    }


async def run_interactive(question: str) -> str:
    """Run the agent in interactive/chat mode, returns raw markdown text."""
    rag_context = ""
    try:
        rag_context = await asyncio.get_event_loop().run_in_executor(
            None, lambda: search_similar_incidents(question, k=2)
        )
    except Exception as e:
        logger.warning(f"RAG retrieval failed: {e}")

    try:
        output = await asyncio.get_event_loop().run_in_executor(
            None, lambda: _invoke_agent(question, rag_context, interactive=True)
        )
        return output or "Aucune réponse de l'agent."
    except Exception as e:
        logger.error(f"Interactive agent failed: {e}")
        return f"Erreur : {e}"
