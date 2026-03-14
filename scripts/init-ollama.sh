#!/bin/sh
# init-ollama.sh — Wait for Ollama to be ready, then pull the configured model.
# This runs once as the `ollama-init` container on startup.

set -e

OLLAMA_HOST="${OLLAMA_HOST:-http://ollama:11434}"
OLLAMA_MODEL="${OLLAMA_MODEL:-llama3.2}"
MAX_WAIT=120   # seconds to wait for Ollama to become ready
INTERVAL=5

echo "[init-ollama] Waiting for Ollama at ${OLLAMA_HOST} ..."
elapsed=0
until curl -sf "${OLLAMA_HOST}/api/tags" > /dev/null 2>&1; do
  if [ $elapsed -ge $MAX_WAIT ]; then
    echo "[init-ollama] ERROR: Ollama did not become ready within ${MAX_WAIT}s. Exiting."
    exit 1
  fi
  echo "[init-ollama] Not ready yet — retrying in ${INTERVAL}s (${elapsed}/${MAX_WAIT}s elapsed)"
  sleep $INTERVAL
  elapsed=$((elapsed + INTERVAL))
done

echo "[init-ollama] Ollama is ready. Checking for model '${OLLAMA_MODEL}' ..."

# Check whether the model is already downloaded
if curl -sf "${OLLAMA_HOST}/api/tags" | grep -q "\"${OLLAMA_MODEL}\""; then
  echo "[init-ollama] Model '${OLLAMA_MODEL}' already present. Nothing to do."
else
  echo "[init-ollama] Pulling model '${OLLAMA_MODEL}' — this may take several minutes on first run ..."
  curl -sf -X POST "${OLLAMA_HOST}/api/pull" \
    -H 'Content-Type: application/json' \
    -d "{\"name\": \"${OLLAMA_MODEL}\"}" \
    | while IFS= read -r line; do
        echo "[init-ollama] $line"
      done
  echo "[init-ollama] Model '${OLLAMA_MODEL}' pulled successfully."
fi

echo "[init-ollama] Initialisation complete."
