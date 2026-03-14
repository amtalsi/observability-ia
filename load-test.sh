#!/usr/bin/env bash
# Générateur de trafic HTTP : requêtes valides + erreurs
# Usage: ./load-test.sh [cycles] [delay_sec]

API="http://localhost:8000"
CYCLES=${1:-20}
DELAY=${2:-0.5}

GREEN='\033[0;32m'; RED='\033[0;31m'; YELLOW='\033[1;33m'; NC='\033[0m'

ok()  { echo -e "${GREEN}✓ $*${NC}"; }
err() { echo -e "${RED}✗ $*${NC}"; }
info(){ echo -e "${YELLOW}→ $*${NC}"; }

echo "=== Load test : ${CYCLES} cycles, délai ${DELAY}s ==="

for i in $(seq 1 $CYCLES); do
    info "── Cycle $i/$CYCLES ──────────────────────"

    # 1. Health check (toujours 200)
    STATUS=$(curl -s -o /dev/null -w "%{http_code}" "$API/health")
    [[ $STATUS == 200 ]] && ok "GET /health → $STATUS" || err "GET /health → $STATUS"

    # 2. Créer une tâche valide
    TASK=$(curl -s -X POST "$API/tasks" \
        -H "Content-Type: application/json" \
        -d "{\"title\": \"Task-$i\", \"description\": \"Cycle $i\"}")
    TASK_ID=$(echo "$TASK" | python3 -c "import sys,json; print(json.load(sys.stdin).get('id',''))" 2>/dev/null)
    [[ -n "$TASK_ID" ]] && ok "POST /tasks → id=$TASK_ID" || err "POST /tasks → $TASK"

    # 3. Lire la tâche créée
    if [[ -n "$TASK_ID" ]]; then
        STATUS=$(curl -s -o /dev/null -w "%{http_code}" "$API/tasks/$TASK_ID")
        [[ $STATUS == 200 ]] && ok "GET /tasks/$TASK_ID → $STATUS" || err "GET /tasks/$TASK_ID → $STATUS"
    fi

    # 4. Lister toutes les tâches
    STATUS=$(curl -s -o /dev/null -w "%{http_code}" "$API/tasks")
    [[ $STATUS == 200 ]] && ok "GET /tasks → $STATUS" || err "GET /tasks → $STATUS"

    # 5. Erreur 404 – tâche inexistante (id aléatoire élevé)
    BAD_ID=$((99000 + RANDOM % 1000))
    STATUS=$(curl -s -o /dev/null -w "%{http_code}" "$API/tasks/$BAD_ID")
    [[ $STATUS == 404 ]] && ok "GET /tasks/$BAD_ID → $STATUS (404 attendu)" || err "GET /tasks/$BAD_ID → $STATUS"

    # 6. Erreur 422 – POST avec payload invalide (title manquant)
    STATUS=$(curl -s -o /dev/null -w "%{http_code}" -X POST "$API/tasks" \
        -H "Content-Type: application/json" \
        -d '{"description": "pas de title"}')
    [[ $STATUS == 422 ]] && ok "POST /tasks (sans title) → $STATUS (422 attendu)" || err "POST /tasks (sans title) → $STATUS"

    # 7. Erreur 404 – DELETE tâche inexistante
    STATUS=$(curl -s -o /dev/null -w "%{http_code}" -X DELETE "$API/tasks/$BAD_ID")
    [[ $STATUS == 404 ]] && ok "DELETE /tasks/$BAD_ID → $STATUS (404 attendu)" || err "DELETE /tasks/$BAD_ID → $STATUS"

    # 8. Route inexistante → 404/405
    STATUS=$(curl -s -o /dev/null -w "%{http_code}" "$API/nonexistent")
    [[ $STATUS =~ ^(404|405) ]] && ok "GET /nonexistent → $STATUS (erreur attendue)" || err "GET /nonexistent → $STATUS"

    sleep "$DELAY"
done

echo ""
echo "=== Terminé. Vérifier Prometheus : rate(http_requests_total[5m]) ==="
