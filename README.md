# Observability AI Stack

> Stack d'observabilité **full-stack** (métriques · logs · traces) couplée à une couche IA locale proactive — analyse automatique des alertes, rapports périodiques dans Grafana, chat interactif en langage naturel. Tout tourne en local avec Docker Compose, sans dépendance cloud.

![Docker](https://img.shields.io/badge/Docker-Compose-2496ED?logo=docker&logoColor=white)
![Python](https://img.shields.io/badge/Python-3.11-3776AB?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688?logo=fastapi&logoColor=white)
![LangChain](https://img.shields.io/badge/LangChain-0.3-1C3C3C?logo=langchain&logoColor=white)
![Grafana](https://img.shields.io/badge/Grafana-11.4-F46800?logo=grafana&logoColor=white)
![Prometheus](https://img.shields.io/badge/Prometheus-latest-E6522C?logo=prometheus&logoColor=white)
![Ollama](https://img.shields.io/badge/Ollama-llama3.1:8b-000000?logo=ollama&logoColor=white)

---

## Table des matières

1. [Vue d'ensemble](#vue-densemble)
2. [Architecture](#architecture)
3. [Services & ports](#services--ports)
4. [Prérequis](#prérequis)
5. [Démarrage rapide](#démarrage-rapide)
6. [Les deux chemins IA](#les-deux-chemins-ia)
7. [Chat interactif — Open WebUI](#chat-interactif--open-webui)
8. [Alertes & webhook AI](#alertes--webhook-ai)
9. [Load testing](#load-testing)
10. [Dashboards Grafana](#dashboards-grafana)
11. [Référence PromQL / LogQL](#référence-promql--logql)
12. [Structure du projet](#structure-du-projet)
13. [Variables d'environnement](#variables-denvironnement)
14. [Développement](#développement)

---

## Vue d'ensemble

Ce projet est un **laboratoire d'observabilité augmenté par l'IA** :

| Pilier | Outils |
|---|---|
| **Métriques** | Prometheus · Node Exporter · postgres-exporter · /metrics FastAPI & Worker |
| **Logs** | Loki · Promtail (collecte Docker automatique) |
| **Traces** | Tempo · OpenTelemetry Collector · instrumentation FastAPI + SQLAlchemy |
| **Alerting** | Alertmanager → webhook → AI Agent |
| **IA proactive** | LangChain ReAct · llama3.1:8b (Ollama) · RAG Qdrant · rapports PostgreSQL |
| **IA interactive** | Open WebUI → AI Agent (OpenAI-compatible) · llama3.1:8b |
| **Visualisation** | Grafana 11.4 — dashboards auto-provisionnés |

**Flux automatique :** Prometheus détecte une anomalie → Alertmanager → webhook → AI Agent analyse métriques + logs + alertes avec LangChain + RAG → rapport structuré dans PostgreSQL → visible dans Grafana.

**Flux interactif :** vous posez une question en langage naturel dans Open WebUI → l'AI Agent interroge Prometheus / Loki / Alertmanager en temps réel → réponse en markdown.

---

## Architecture

```
╔══════════════════════════════════════════════════════════════════╗
║  🤖  AI LAYER                                                    ║
║                                                                  ║
║  ┌─────────────────────────────┐  ┌──────────────────────────┐  ║
║  │ ⚡ Chemin PROACTIF           │  │ 💬 Chemin INTERACTIF     │  ║
║  │                             │  │                          │  ║
║  │ Alertmanager ──► AI Agent   │  │ Open WebUI               │  ║
║  │ (webhook)      :8001        │  │ :8080                    │  ║
║  │                LangChain    │  │      │ /v1/chat/          │  ║
║  │                llama3.1:8b  │  │      ▼ completions       │  ║
║  │                     │       │  │ AI Agent :8001           │  ║
║  │              ┌──────┘       │  │ LangChain + tools        │  ║
║  │              ▼              │  │ llama3.1:8b              │  ║
║  │  ┌──────────────────────┐   │  └──────────────────────────┘  ║
║  │  │ 🗄️  Qdrant  :6333    │   │                                ║
║  │  │ RAG : similarité     │   │                                ║
║  │  │ vectorielle          │   │                                ║
║  │  │ nomic-embed-text     │   │                                ║
║  │  └──────────────────────┘   │                                ║
║  │  rapport → PostgreSQL       │                                ║
║  └─────────────────────────────┘                                ║
╠══════════════════════════════════════════════════════════════════╣
║  📡  OBSERVABILITY LAYER                                         ║
║                                                                  ║
║  Prometheus :9090  Loki :3100  Alertmanager :9093  Grafana :3001 ║
║       │               │              │               │           ║
║  Tempo :3200   OTel-Collector :4317  │          AI Reports ✓    ║
╠══════════════════════════════════════╪═══════════════════════════╣
║  ⚙️  APPLICATION LAYER               ▼                           ║
║                                                                  ║
║  API FastAPI :8000  ◄─R/W─►  PostgreSQL :5432  ◄─poll─►  Worker ║
║       │                            │                    :9091   ║
║       │ /metrics                   │ ai_reports                 ║
║       │                            │                            ║
║  OTel traces                  pg-exporter :9187                  ║
║  Promtail → Loki              Node Exporter :9100                ║
╚══════════════════════════════════════════════════════════════════╝
```

### Flux de données détaillé

```
           scrape /metrics (15s)
Prometheus ◄────────────────── API :8000/metrics
           ◄────────────────── Worker :9091/metrics
           ◄────────────────── postgres-exporter :9187
           ◄────────────────── node-exporter :9100
           ◄────────────────── otel-collector :8889

Loki       ◄── Promtail ◄── Docker socket (tous les containers)

Tempo      ◄── OTel Collector :4317 ◄── API (OTLP gRPC)
                                    ◄── Worker (OTLP gRPC)

Alertmanager ◄── Prometheus (règles alert-rules.yml)
             ──► POST /webhook/alert ──► AI Agent

AI Agent ──► query_prometheus / query_loki / get_active_alerts
         ──► Qdrant (search_similar_incidents → RAG context)
         ──► save_report() ──► PostgreSQL.ai_reports
         ──► index_report() ──► Qdrant (historique)

Grafana ◄── PostgreSQL (datasource ai_reports)
        ◄── Prometheus / Loki / Tempo (datasources manuelles)
```

---

## Services & ports

| Service | Image | Port(s) | URL locale | Rôle |
|---|---|---|---|---|
| **Grafana** | grafana/grafana:11.4.0 | 3001→3000 | http://localhost:3001 | Dashboards (login: admin/admin) |
| **Prometheus** | prom/prometheus:latest | 9090 | http://localhost:9090 | Scraping métriques, évaluation règles |
| **Loki** | grafana/loki:latest | 3100 | http://localhost:3100 | Agrégation logs |
| **Tempo** | grafana/tempo:latest | 3200 | http://localhost:3200 | Stockage traces (rétention 48h) |
| **Alertmanager** | prom/alertmanager:latest | 9093 | http://localhost:9093 | Gestion alertes → webhook AI |
| **OTel Collector** | otel/opentelemetry-collector-contrib | 4317/4318 | — | Réception OTLP → Tempo + Prometheus |
| **Node Exporter** | prom/node-exporter:latest | 9100 | http://localhost:9100/metrics | Métriques système hôte |
| **PostgreSQL** | postgres:16 | 5432 | — | BDD applicative + table ai_reports |
| **postgres-exporter** | prometheuscommunity/postgres-exporter | 9187 | http://localhost:9187/metrics | Métriques PostgreSQL → Prometheus |
| **API FastAPI** | (build local) | 8000 | http://localhost:8000/docs | CRUD /tasks · /metrics · traces OTLP |
| **Worker** | (build local) | 9091 | http://localhost:9091/metrics | Poll PostgreSQL · traite tâches · métriques |
| **Promtail** | grafana/promtail:latest | — | — | Collecte Docker logs → Loki |
| **AI Agent** | (build local) | 8001 | http://localhost:8001/docs | LangChain + RAG + API OpenAI-compatible |
| **Ollama** | ollama/ollama:latest | 11434 | http://localhost:11434 | LLM local (llama3.1:8b + nomic-embed-text) |
| **Qdrant** | qdrant/qdrant:latest | 6333/6334 | http://localhost:6333/dashboard | Base vectorielle RAG |
| **Open WebUI** | ghcr.io/open-webui/open-webui:main | 8080 | http://localhost:8080 | Interface de chat (branché sur AI Agent) |
| **n8n** | n8nio/n8n:latest | 5678 | http://localhost:5678 | Webhooks optionnels (login: admin/admin) |

> **Note port 3001** : Grafana écoute sur 3001 car le port 3000 peut être occupé par un service système.

---

## Prérequis

| Outil | Version minimale | Notes |
|---|---|---|
| Docker Engine | ≥ 24 | |
| Docker Compose | v2 (`docker compose`) | Le plugin v2 est inclus dans Docker Desktop |
| RAM disponible | **≥ 8 Go** | llama3.1:8b nécessite ~5 Go de RAM |
| Espace disque | **≥ 15 Go** | Modèles Ollama (~7 Go) + volumes Docker |
| `curl` | any | Pour le load-test et les vérifications |
| `python3` | ≥ 3.8 | Uniquement pour le load-test (parsing JSON) |

```bash
# Vérifier Docker Compose v2
docker compose version
# → Docker Compose version v2.x.x
```

---

## Démarrage rapide

### 1. Cloner le dépôt

```bash
git clone https://github.com/<votre-user>/observability-ai.git
cd observability-ai
```

### 2. Lancer la stack

```bash
# Premier démarrage — build des images applicatives
docker compose up -d --build

# Relances suivantes (images déjà buildées)
docker compose up -d
```

### 3. Vérifier que tout est up

```bash
docker compose ps
```

Tous les containers doivent afficher **Up**. Exemple de sortie attendue :

```
NAME                STATUS
ai-agent            Up
alertmanager        Up
api                 Up
grafana             Up
loki                Up
n8n                 Up
node-exporter       Up
ollama              Up
open-webui          Up (healthy)
otel-collector      Up
postgres            Up
postgres-exporter   Up
prometheus          Up
promtail            Up
qdrant              Up
tempo               Up
worker              Up
```

### 4. Attendre le téléchargement des modèles Ollama

Au **premier démarrage**, l'AI Agent télécharge automatiquement :

| Modèle | Taille | Usage |
|---|---|---|
| `llama3.1:8b` | ~4.7 Go | Analyses proactives + chat interactif |
| `nomic-embed-text` | ~270 Mo | Embeddings Qdrant (RAG) |

Suivre la progression :

```bash
docker logs -f ai-agent
# → "Pulling llama3.1:8b…"
# → "Model llama3.1:8b pulled successfully"
# → "Model nomic-embed-text pulled successfully"
# → "AI Agent started" {"interval_minutes": 15}
```

La première analyse planifiée s'exécute **15 minutes** après le démarrage.

### 5. Accéder aux interfaces

| Interface | URL | Identifiants |
|---|---|---|
| **Grafana** | http://localhost:3001 | admin / admin |
| **Open WebUI** (chat AI) | http://localhost:8080 | Créer un compte au 1er accès |
| **AI Agent API** | http://localhost:8001/docs | — |
| **Prometheus** | http://localhost:9090 | — |
| **Alertmanager** | http://localhost:9093 | — |
| **Qdrant Dashboard** | http://localhost:6333/dashboard | — |
| **n8n** | http://localhost:5678 | admin / admin |

### 6. Générer du trafic (optionnel)

```bash
chmod +x load-test.sh

# 20 cycles, 0.5s entre chaque (défaut)
./load-test.sh

# 50 cycles, 1s de délai
./load-test.sh 50 1
```

Le script génère des requêtes valides (200) et des erreurs intentionnelles (404, 422) pour alimenter Prometheus, Loki et les dashboards.

### 7. Arrêter la stack

```bash
# Arrêt (volumes conservés)
docker compose down

# Arrêt + suppression des volumes (reset complet)
docker compose down -v
```

---

## Les deux chemins IA

### ⚡ Chemin proactif — AI Agent + RAG

L'agent s'exécute automatiquement **sans intervention humaine** :

```
Trigger
  ├── Alertmanager (POST /webhook/alert)  → en cas d'alerte firing
  └── APScheduler                         → toutes les 15 min

       ▼
Qdrant.search_similar_incidents(question, k=3)
       │  RAG : contexte historique des incidents passés
       ▼
LangChain ReAct loop (max 6 itérations)
  ├── query_prometheus(promql)   → santé services, taux erreurs, latences
  ├── query_loki(logql)          → logs d'erreurs récents
  └── get_active_alerts()        → alertes Alertmanager actives
       ▼
_parse_report() → JSON {summary, analysis, recommendations, severity}
       ▼
PostgreSQL.ai_reports  →  Grafana dashboard "AI Observability Reports"
Qdrant.index_report()  →  enrichissement RAG pour les analyses suivantes
```

**Déclencher une analyse manuelle :**

```bash
curl -X POST http://localhost:8001/analyze | python3 -m json.tool
```

**Consulter les rapports :**

```bash
curl http://localhost:8001/reports | python3 -m json.tool
```

### 💬 Chemin interactif — Open WebUI

Open WebUI est configuré pour utiliser l'AI Agent comme **backend OpenAI-compatible** (`/v1/chat/completions`). Le modèle disponible est `observability-ai`.

```
Question utilisateur (Open WebUI)
       ▼
POST http://ai-agent:8001/v1/chat/completions
       ▼
LangChain ReAct loop
  ├── query_prometheus  →  Prometheus
  ├── query_loki        →  Loki
  └── get_active_alerts →  Alertmanager
       ▼
Réponse en markdown dans le chat
```

> **Important** : le modèle `observability-ai` est différent des modèles Ollama bruts. Il a accès aux outils d'observabilité en temps réel.

---

## Chat interactif — Open WebUI

### Première utilisation

1. Ouvrir http://localhost:8080
2. Créer un compte (premier compte = admin)
3. Dans la zone de saisie, **sélectionner le modèle `observability-ai`** dans le menu déroulant (en haut ou dans le sélecteur de modèle)
4. Poser votre question en langage naturel

### Exemples de questions

```
"Quels services sont actuellement down ?"
"Montre-moi le taux d'erreurs HTTP de l'API sur les 5 dernières minutes"
"Y a-t-il des alertes actives en ce moment ?"
"Montre-moi les derniers logs d'erreur du service api"
"Combien de tâches le worker a-t-il traitées récemment ?"
"Quel est l'état de santé global du système ?"
"Combien de connexions actives sur PostgreSQL ?"
"Analyse les performances de l'API"
```

### Comment ça marche

L'AI Agent reçoit la question, l'IA (llama3.1:8b) décide quels outils appeler, exécute les requêtes PromQL/LogQL, et synthétise une réponse structurée en français.

---

## Alertes & webhook AI

### Règles d'alerte configurées

| Alerte | Condition | Sévérité | Délai |
|---|---|---|---|
| `ApiDown` | `up{job="api"} == 0` | critical | 1 min |
| `WorkerDown` | `up{job="worker"} == 0` | critical | 1 min |
| `HighHttpErrorRate` | `rate(http_requests_total{status=~"5..",job="api"}[5m]) > 0.05` | warning | 2 min |
| `PostgresExporterDown` | `up{job="postgres-exporter"} == 0` | warning | 1 min |

### Flux alerte → analyse IA

```
Prometheus évalue les règles toutes les 15s
       │  condition remplie pendant > délai
       ▼
Alertmanager reçoit l'alerte
       │  route: receiver "ai-agent"
       ▼
POST http://ai-agent:8001/webhook/alert
  { "alerts": [{ "labels": { "alertname": "ApiDown", "severity": "critical" }, "status": "firing" }] }
       ▼
AI Agent lance run_analysis(trigger="alert", alert_name="ApiDown", severity="critical")
       ▼
Rapport sauvegardé dans PostgreSQL + indexé dans Qdrant
       ▼
Visible dans Grafana → AI Observability Reports
```

### Simuler une alerte

```bash
# Stopper l'API pour déclencher ApiDown
docker compose stop api
# Attendre ~1 min → Alertmanager → AI Agent analyse automatiquement

# Vérifier l'alerte dans Alertmanager
curl http://localhost:9093/api/v2/alerts | python3 -m json.tool

# Relancer l'API
docker compose start api
```

---

## Load testing

Le script `load-test.sh` génère du trafic mixte (succès + erreurs) pour alimenter les métriques Prometheus et les logs Loki.

```bash
chmod +x load-test.sh
./load-test.sh [cycles] [delay_sec]

# Exemples
./load-test.sh          # 20 cycles, 0.5s (défaut)
./load-test.sh 100 0.2  # 100 cycles rapides
./load-test.sh 50 2     # 50 cycles lents
```

**Requêtes générées par cycle :**

| Requête | Code attendu | Rôle |
|---|---|---|
| `GET /health` | 200 | Health check |
| `POST /tasks` | 201 | Créer une tâche |
| `GET /tasks/:id` | 200 | Lire la tâche créée |
| `GET /tasks` | 200 | Liste toutes les tâches |
| `GET /tasks/99xxx` | 404 | Erreur 4xx intentionnelle |
| `POST /tasks` (sans title) | 422 | Erreur validation |
| `DELETE /tasks/99xxx` | 404 | Erreur 4xx intentionnelle |
| `GET /nonexistent` | 404 | Route inconnue |

Après le load test, vérifier dans Prometheus :

```promql
rate(http_requests_total[5m])
rate(http_requests_total{status="4xx"}[5m])
```

---

## Dashboards Grafana

### Dashboard auto-provisionné

Le dashboard **AI Observability Reports** est provisionné automatiquement au démarrage.

**Chemin :** Grafana → Dashboards → AI Observability → AI Observability Reports

| Panel | Contenu |
|---|---|
| Stats | Total analyses · Analyses 24h · Dernière sévérité · Alertes analysées |
| Timeseries | Fréquence des analyses dans le temps |
| Table rapports | 50 derniers rapports : heure, déclencheur, alerte, sévérité, résumé, durée |
| Détail dernière analyse | Analyse complète + recommandations du rapport le plus récent |

### Datasources à configurer manuellement

Grafana → **Connections → Add new connection** :

| Datasource | URL interne Docker | Type |
|---|---|---|
| Prometheus | `http://prometheus:9090` | Prometheus |
| Loki | `http://loki:3100` | Loki |
| Tempo | `http://tempo:3200` | Tempo |
| **PostgreSQL** | `postgres:5432` · db: `appdb` | **Auto-provisionné ✓** |

### Dashboard PostgreSQL officiel

Dans Grafana → **Dashboards → Import** → ID **9628** (PostgreSQL Database)

---

## Référence PromQL / LogQL

### PromQL

```promql
# Services actifs (1 = up, 0 = down)
up

# Taux de requêtes HTTP de l'API (toutes routes)
rate(http_requests_total{job="api"}[5m])

# Taux d'erreurs 4xx
rate(http_requests_total{job="api", status="4xx"}[5m])

# Taux d'erreurs 5xx
rate(http_requests_total{job="api", status="5xx"}[5m])

# Latence p95 de l'API
histogram_quantile(0.95, rate(http_request_duration_seconds_bucket{job="api"}[5m]))

# Tâches traitées par le worker (compteur)
worker_tasks_processed_total

# Taux de traitement du worker
rate(worker_tasks_processed_total[5m])

# Santé PostgreSQL
pg_up

# Connexions actives PostgreSQL
pg_stat_database_numbackends{datname="appdb"}

# CPU hôte (%)
100 - (avg(rate(node_cpu_seconds_total{mode="idle"}[5m])) * 100)

# Mémoire disponible (Mo)
node_memory_MemAvailable_bytes / 1024 / 1024
```

> **Note labels http_requests_total** : le label `status` contient des classes (`"2xx"`, `"4xx"`, `"5xx"`), jamais des codes exacts (200, 404…).

### LogQL

```logql
# Tous les logs de l'API
{service="api"}

# Logs d'erreur du worker
{service="worker"} |= "error"

# Logs JSON niveau ERROR
{service="api"} | json | level="ERROR"

# Logs de l'AI Agent
{service="ai-agent"}

# Tâches traitées par le worker
{service="worker"} |= "Task done"

# Logs d'un container spécifique (nom Docker)
{container="api"} | json
```

---

## Structure du projet

```
observability-ai/
│
├── docker-compose.yaml              # Stack complète (17 services)
│
├── app/
│   ├── api/                         # FastAPI · Prometheus · OTel traces
│   │   ├── main.py                  # CRUD /tasks + /metrics + instrumentation
│   │   ├── models.py                # SQLAlchemy Task model
│   │   ├── database.py              # Engine + session
│   │   ├── requirements.txt
│   │   └── Dockerfile
│   │
│   ├── worker/                      # Worker Python · Prometheus metrics · OTel
│   │   ├── main.py                  # Poll PostgreSQL 5s · traite tâches · :9091/metrics
│   │   ├── requirements.txt
│   │   └── Dockerfile
│   │
│   └── ai-agent/                    # Agent proactif LangChain + RAG
│       ├── main.py                  # FastAPI + APScheduler + webhook + /v1/chat/completions
│       ├── agent.py                 # LangChain ReAct · 3 outils · fallback text tool calls
│       ├── vectorstore.py           # Qdrant : indexing + similarity search
│       ├── database.py              # Table ai_reports (PostgreSQL)
│       ├── requirements.txt
│       └── Dockerfile
│
├── grafana/
│   └── provisioning/
│       ├── datasources/
│       │   └── postgres.yaml        # PostgreSQL datasource auto-provisionné
│       └── dashboards/
│           ├── providers.yaml       # Déclaration des dashboard providers
│           └── ai-reports.json      # Dashboard AI Reports
│
├── n8n-workflows/                   # Workflows optionnels (à importer dans n8n)
│   ├── metrics.json                 # GET Prometheus via webhook
│   ├── logs.json                    # GET Loki via webhook
│   └── alerts.json                  # GET Alertmanager via webhook
│
├── open-webui-functions/
│   └── observability_tools.py       # Tool Open WebUI legacy (remplacé par /v1/chat)
│
├── load-test.sh                     # Générateur de trafic HTTP (curl)
│
├── prometheus.yml                   # Scrape configs + alerting
├── alert-rules.yml                  # Règles d'alerte (ApiDown, WorkerDown, HighHttpErrorRate…)
├── alert-config.yaml                # Alertmanager → webhook ai-agent:8001
├── alert-email-template.tmpl        # Template email optionnel
├── loki-config.yaml                 # Configuration Loki
├── tempo.yaml                       # Configuration Tempo
├── otel-collector-config.yaml       # Pipeline OTel (OTLP → Tempo + Prometheus)
├── promtail-config.yaml             # Collecte Docker logs → Loki
│
└── quick-start.html                 # Documentation HTML interactive
```

---

## Variables d'environnement

### AI Agent (`app/ai-agent/`)

| Variable | Défaut | Description |
|---|---|---|
| `DATABASE_URL` | `postgresql://user:password@postgres:5432/appdb` | PostgreSQL connection string |
| `OLLAMA_URL` | `http://ollama:11434` | URL Ollama (LLM + embeddings) |
| `PROMETHEUS_URL` | `http://prometheus:9090` | URL Prometheus |
| `LOKI_URL` | `http://loki:3100` | URL Loki |
| `ALERTMANAGER_URL` | `http://alertmanager:9093` | URL Alertmanager |
| `ANALYSIS_INTERVAL_MINUTES` | `15` | Intervalle analyses planifiées |
| `QDRANT_HOST` | `qdrant` | Host Qdrant |
| `QDRANT_PORT` | `6333` | Port Qdrant |

### Worker (`app/worker/`)

| Variable | Défaut | Description |
|---|---|---|
| `DATABASE_URL` | `postgresql://user:password@postgres:5432/appdb` | PostgreSQL connection string |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | `http://otel-collector:4317` | Endpoint OTel Collector |
| `OTEL_SERVICE_NAME` | `worker` | Nom du service dans les traces |
| `POLL_INTERVAL` | `5` | Intervalle poll PostgreSQL (secondes) |
| `METRICS_PORT` | `9091` | Port exposition métriques Prometheus |

### API (`app/api/`)

| Variable | Défaut | Description |
|---|---|---|
| `DATABASE_URL` | `postgresql://user:password@postgres:5432/appdb` | PostgreSQL connection string |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | `http://otel-collector:4317` | Endpoint OTel Collector |
| `OTEL_SERVICE_NAME` | `api` | Nom du service dans les traces |

### PostgreSQL

| Variable | Valeur | Description |
|---|---|---|
| `POSTGRES_USER` | `user` | Utilisateur BDD |
| `POSTGRES_PASSWORD` | `password` | Mot de passe BDD |
| `POSTGRES_DB` | `appdb` | Nom de la base |

> **Production** : remplacer les identifiants par des secrets via Docker secrets ou un fichier `.env`.

---

## Développement

### Reconstruire un seul service

```bash
# Rebuilder et redémarrer uniquement l'AI Agent
docker compose up -d --build ai-agent

# Rebuilder l'API
docker compose up -d --build api
```

### Suivre les logs en temps réel

```bash
# Tous les services
docker compose logs -f

# Service spécifique
docker compose logs -f ai-agent
docker compose logs -f worker
docker compose logs -f api
```

### API Endpoints

#### API FastAPI (`localhost:8000`)

```bash
# Swagger UI
open http://localhost:8000/docs

# Health check
curl http://localhost:8000/health

# Créer une tâche
curl -X POST http://localhost:8000/tasks \
  -H "Content-Type: application/json" \
  -d '{"title": "Ma tâche", "description": "Description"}'

# Lister les tâches
curl http://localhost:8000/tasks

# Métriques Prometheus
curl http://localhost:8000/metrics
```

#### AI Agent (`localhost:8001`)

```bash
# Swagger UI
open http://localhost:8001/docs

# Santé
curl http://localhost:8001/health

# Déclencher une analyse manuelle
curl -X POST http://localhost:8001/analyze | python3 -m json.tool

# Consulter les rapports (20 derniers)
curl http://localhost:8001/reports | python3 -m json.tool

# Modèles disponibles (OpenAI-compatible)
curl http://localhost:8001/v1/models | python3 -m json.tool

# Chat direct (sans Open WebUI)
curl -X POST http://localhost:8001/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "observability-ai",
    "messages": [{"role": "user", "content": "Quels services sont down ?"}]
  }' | python3 -m json.tool
```

#### Worker métriques (`localhost:9091`)

```bash
curl http://localhost:9091/metrics | grep worker
# worker_tasks_processed_total
# worker_tasks_errors_total
# worker_up
```

### Qdrant — Explorer les vecteurs RAG

```bash
# Collections disponibles
curl http://localhost:6333/collections | python3 -m json.tool

# Infos sur la collection observability_reports
curl http://localhost:6333/collections/observability_reports | python3 -m json.tool

# Ou via l'interface web
open http://localhost:6333/dashboard
```

### Rechargement à chaud de la configuration Prometheus

```bash
curl -X POST http://localhost:9090/-/reload
```

---

## Schéma des métriques clés

```
Métrique                          Type      Labels principaux
────────────────────────────────────────────────────────────
http_requests_total               counter   job, handler, method, status (2xx/4xx/5xx)
http_request_duration_seconds     histogram job, handler, method
worker_tasks_processed_total      counter   —
worker_tasks_errors_total         counter   —
worker_up                         gauge     —
up                                gauge     job, instance
pg_up                             gauge     —
pg_stat_database_numbackends      gauge     datname
node_cpu_seconds_total            counter   mode, cpu
node_memory_MemAvailable_bytes    gauge     —
```

---

## Contribuer

1. Fork le dépôt
2. Créer une branche (`git checkout -b feature/ma-feature`)
3. Committer (`git commit -m 'feat: description'`)
4. Pusher (`git push origin feature/ma-feature`)
5. Ouvrir une Pull Request

---

## Licence

MIT — libre d'utilisation, modification et distribution.

---

*Stack construite avec : FastAPI · LangChain · Ollama · Prometheus · Grafana · Loki · Tempo · OpenTelemetry · Qdrant · PostgreSQL · Docker Compose*
