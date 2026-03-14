# observability-ia

> **Full observability stack (metrics · logs · traces) coupled with a proactive local AI layer — automatic alert analysis and periodic reports in Grafana, without manual intervention.**

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                         Data Sources                            │
│  node-exporter  │  cAdvisor  │  Application OTLP traces        │
└────────┬───────────────┬──────────────────┬────────────────────┘
         │               │                  │
         ▼               ▼                  ▼
┌──────────────┐  ┌─────────────┐  ┌──────────────┐
│  Prometheus  │  │    Loki     │  │    Tempo     │
│  (metrics)   │  │   (logs)    │  │  (traces)    │
└──────┬───────┘  └──────┬──────┘  └──────┬───────┘
       │                 │                │
       └─────────────────┴────────────────┘
                         │
                         ▼
               ┌──────────────────┐
               │     Grafana      │  ◄── annotations written by N8N
               │  (dashboards &   │
               │   annotations)   │
               └──────────────────┘
                         │  alerts via webhook
                         ▼
               ┌──────────────────┐          ┌─────────────────┐
               │   Alertmanager   │─────────►│      N8N        │
               │  (alert routing) │          │  (automation)   │
               └──────────────────┘          └────────┬────────┘
                                                      │
                                                      ▼
                                             ┌─────────────────┐
                                             │     Ollama      │
                                             │  (local LLM)    │
                                             └─────────────────┘
                                                      │
                                             ┌─────────────────┐
                                             │   Open WebUI    │
                                             │ (chat interface)│
                                             └─────────────────┘
```

### AI Automation Flows

| Flow | Trigger | Steps | Output |
|------|---------|-------|--------|
| **Alert Analysis** | Alertmanager fires an alert → webhook to N8N | Parse alert → Query Prometheus context → Build prompt → Ollama LLM → Post Grafana annotation | Instant AI analysis visible on every dashboard |
| **Periodic Report** | Daily cron at 08:00 | Query 24h CPU/memory/errors/availability → Build report prompt → Ollama LLM → Post Grafana annotation | Daily health summary with findings & recommendations |

---

## Services

| Service | Port | Purpose |
|---------|------|---------|
| **Grafana** | 3000 | Dashboards, annotations, alerting UI |
| **Prometheus** | 9090 | Metrics collection and evaluation |
| **Alertmanager** | 9093 | Alert routing → N8N webhook |
| **Loki** | 3100 | Log aggregation backend |
| **Tempo** | 3200 | Distributed tracing backend |
| **Node Exporter** | 9100 | Host CPU/memory/disk/network metrics |
| **cAdvisor** | 8080 | Docker container metrics |
| **Ollama** | 11434 | Local LLM API (llama3.2 by default) |
| **Open WebUI** | 8501 | Browser-based chat UI for Ollama |
| **N8N** | 5678 | Workflow automation (alert→AI→annotation) |

---

## Quick Start

### Prerequisites
- Docker ≥ 24 and Docker Compose v2
- At least **8 GB RAM** (16 GB recommended when using larger LLMs)
- At least **20 GB free disk** (LLM model files can be several GB)

### 1. Configure environment

```bash
cp .env.example .env   # or copy .env and edit
```

Edit `.env` and set at minimum:
- `GRAFANA_ADMIN_PASSWORD` — Grafana admin password
- `N8N_BASIC_AUTH_PASSWORD` — N8N UI password
- `OLLAMA_MODEL` — LLM model to use (default: `llama3.2`)

### 2. Start the stack

```bash
docker compose up -d
```

The first run will:
1. Pull all Docker images
2. Start all services
3. The `ollama-init` container will automatically pull the configured LLM model

> ℹ️ The `ollama-init` step may take **5–20 minutes** on first run depending on your internet connection and the model size.

### 3. Access the UIs

| UI | URL | Credentials |
|----|-----|-------------|
| Grafana | http://localhost:3000 | admin / `$GRAFANA_ADMIN_PASSWORD` |
| N8N | http://localhost:5678 | admin / `$N8N_BASIC_AUTH_PASSWORD` |
| Prometheus | http://localhost:9090 | — |
| Alertmanager | http://localhost:9093 | — |
| Open WebUI | http://localhost:8501 | — |

### 4. Import N8N Workflows

The N8N workflows are stored in `n8n/workflows/` and must be imported once:

1. Open http://localhost:5678
2. Go to **Workflows** → **Import from file**
3. Import `n8n/workflows/alert-analysis.json`
4. Import `n8n/workflows/periodic-reports.json`
5. In each workflow, update the **Grafana Basic Auth** credential with your Grafana password
6. Activate both workflows

> 💡 After import, the alert analysis workflow listens at `http://localhost:5678/webhook/alertmanager` — Alertmanager is pre-configured to call this endpoint.

---

## Dashboards

Two dashboards are pre-provisioned in Grafana under the **Observability-IA** folder:

### System Overview
- Host CPU, Memory, Disk gauges
- CPU & Memory over time
- Network I/O and Disk I/O
- Container CPU & Memory
- Prometheus scrape target health table

### AI Analysis & Reports
- Active alert count, CPU/Memory stat panels
- Ollama and N8N status
- Alert history timeline (annotated by AI analyses)
- Error log stream from Loki
- Firing alerts table

AI analyses and daily reports appear as **colour-coded annotations** on both dashboards:
- 🟡 Warning-level alerts → orange annotation
- 🔴 Critical-level alerts → red annotation
- 📊 Daily reports → green annotation

---

## Alert Rules

Pre-configured Prometheus alert rules (`prometheus/rules/alerts.yml`):

| Alert | Threshold | Severity |
|-------|-----------|----------|
| HighCPUUsage | > 80% for 5m | warning |
| CriticalCPUUsage | > 95% for 2m | critical |
| HighMemoryUsage | > 85% for 5m | warning |
| CriticalMemoryUsage | > 95% for 2m | critical |
| DiskSpaceLow | < 15% free for 5m | warning |
| DiskSpaceCritical | < 5% free for 1m | critical |
| ContainerHighCPU | > 80% for 5m | warning |
| ContainerHighMemory | > 90% of limit for 5m | warning |
| PrometheusTargetDown | target down for 2m | critical |
| OllamaDown | Ollama unreachable for 2m | warning |
| LokiDown | Loki unreachable for 2m | critical |

---

## GPU Acceleration (optional)

To use GPU for faster LLM inference, uncomment the `deploy` block in the `ollama` service in `docker-compose.yml`:

```yaml
deploy:
  resources:
    reservations:
      devices:
        - driver: nvidia
          count: 1
          capabilities: [gpu]
```

Requires [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/install-guide.html).

---

## Changing the LLM Model

Edit `.env`:
```bash
OLLAMA_MODEL=mistral        # or llama3, gemma2, phi3, etc.
```

Then restart the init container to pull the new model:
```bash
docker compose restart ollama-init
```

Popular models and their sizes:
| Model | Size | Notes |
|-------|------|-------|
| `llama3.2` | ~2 GB | Good quality, fast, **default** |
| `llama3` | ~4.7 GB | Higher quality |
| `mistral` | ~4.1 GB | Strong reasoning |
| `gemma2` | ~5 GB | Google's model |
| `phi3` | ~2.3 GB | Fast, lightweight |

---

## Sending Traces

Your applications can send traces to Tempo via:
- **OTLP gRPC**: `localhost:4317`
- **OTLP HTTP**: `localhost:4318`

Example (Python with OpenTelemetry):
```python
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
exporter = OTLPSpanExporter(endpoint="http://localhost:4317", insecure=True)
```

---

## Stopping the Stack

```bash
docker compose down          # stop but keep volumes
docker compose down -v       # stop and delete all data
```

---

## Project Structure

```
observability-ia/
├── docker-compose.yml          # Main orchestration
├── .env                        # Environment variables (not committed)
├── prometheus/
│   ├── prometheus.yml          # Scrape configs
│   └── rules/
│       └── alerts.yml          # Alert rules
├── alertmanager/
│   └── alertmanager.yml        # Alert routing → N8N
├── loki/
│   └── loki-config.yml         # Log aggregation config
├── promtail/
│   └── promtail-config.yml     # Docker log scraping
├── tempo/
│   └── tempo.yml               # Tracing backend config
├── grafana/
│   ├── provisioning/
│   │   ├── datasources/        # Auto-provision Prometheus, Loki, Tempo
│   │   ├── dashboards/         # Dashboard loader config
│   │   └── alerting/           # Contact points (→ N8N)
│   └── dashboards/
│       ├── system-overview.json    # System metrics dashboard
│       └── ai-analysis.json        # AI reports & alerts dashboard
├── n8n/
│   └── workflows/
│       ├── alert-analysis.json     # Alertmanager → Ollama → Grafana
│       └── periodic-reports.json   # Daily report → Ollama → Grafana
└── scripts/
    └── init-ollama.sh          # Pull LLM model on startup
```
