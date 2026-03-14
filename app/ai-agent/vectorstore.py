"""
Qdrant vector store for RAG (Retrieval Augmented Generation).

Indexed documents:
  - AI reports (summary + analysis + recommendations)
  - Log excerpts (error logs from Loki)
  - Alert events

Embedding model: nomic-embed-text (via Ollama, 768 dimensions)
"""
import os
import logging
from typing import Optional

from langchain_qdrant import QdrantVectorStore
from langchain_ollama import OllamaEmbeddings
from langchain_core.documents import Document
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams

logger = logging.getLogger("ai-agent.vectorstore")

QDRANT_HOST = os.getenv("QDRANT_HOST", "qdrant")
QDRANT_PORT = int(os.getenv("QDRANT_PORT", "6333"))
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://ollama:11434")
COLLECTION = "observability"
EMBED_MODEL = "nomic-embed-text"
VECTOR_DIM = 768  # nomic-embed-text output size

_client: Optional[QdrantClient] = None
_store: Optional[QdrantVectorStore] = None


def _get_client() -> QdrantClient:
    global _client
    if _client is None:
        _client = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT)
    return _client


def _get_embeddings() -> OllamaEmbeddings:
    return OllamaEmbeddings(model=EMBED_MODEL, base_url=OLLAMA_URL)


def init_collection() -> None:
    """Create Qdrant collection if it doesn't exist."""
    try:
        client = _get_client()
        names = [c.name for c in client.get_collections().collections]
        if COLLECTION not in names:
            client.create_collection(
                collection_name=COLLECTION,
                vectors_config=VectorParams(size=VECTOR_DIM, distance=Distance.COSINE),
            )
            logger.info(f"Qdrant collection '{COLLECTION}' created")
        else:
            logger.info(f"Qdrant collection '{COLLECTION}' already exists")
    except Exception as e:
        logger.warning(f"Qdrant init failed (will retry): {e}")


def _get_store() -> QdrantVectorStore:
    global _store
    if _store is None:
        _store = QdrantVectorStore(
            client=_get_client(),
            collection_name=COLLECTION,
            embedding=_get_embeddings(),
        )
    return _store


# ── Indexing ───────────────────────────────────────────────────────────────────

def index_report(report: dict) -> None:
    """Index an AI report for future similarity search."""
    try:
        content = (
            f"[{report.get('trigger_type','').upper()}] {report.get('alert_name','')}\n"
            f"Sévérité: {report.get('severity','')}\n"
            f"Résumé: {report.get('summary','')}\n"
            f"Analyse: {report.get('analysis','')}\n"
            f"Recommandations: {report.get('recommendations','')}"
        )
        doc = Document(
            page_content=content[:3000],
            metadata={
                "type": "report",
                "trigger_type": report.get("trigger_type", ""),
                "alert_name": report.get("alert_name", ""),
                "severity": report.get("severity", "ok"),
            },
        )
        _get_store().add_documents([doc])
        logger.info("Report indexed in Qdrant", extra={"alert": report.get("alert_name")})
    except Exception as e:
        logger.warning(f"Failed to index report in Qdrant: {e}")


def index_logs(logs: str, service: str, level: str = "error") -> None:
    """Index log excerpts for semantic search."""
    if not logs or "No logs found" in logs:
        return
    try:
        doc = Document(
            page_content=f"[LOGS] service={service} level={level}\n{logs[:2000]}",
            metadata={"type": "logs", "service": service, "level": level},
        )
        _get_store().add_documents([doc])
    except Exception as e:
        logger.warning(f"Failed to index logs in Qdrant: {e}")


# ── Retrieval ──────────────────────────────────────────────────────────────────

def search_similar_incidents(query: str, k: int = 3) -> str:
    """
    Search Qdrant for past incidents similar to the current query.
    Returns a formatted string ready to inject into the agent prompt.
    """
    try:
        docs = _get_store().similarity_search(query, k=k)
        if not docs:
            return ""
        parts = []
        for i, doc in enumerate(docs, 1):
            meta = doc.metadata
            header = f"Incident passé #{i} [{meta.get('trigger_type','?')}] {meta.get('alert_name','')} (sévérité: {meta.get('severity','?')})"
            parts.append(f"{header}\n{doc.page_content[:600]}")
        return "\n\n".join(parts)
    except Exception as e:
        logger.warning(f"Qdrant similarity search failed: {e}")
        return ""
