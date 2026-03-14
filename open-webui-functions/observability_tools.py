"""
title: Observability Tools
author: admin
description: Interroge Prometheus (métriques), Loki (logs) et Alertmanager (alertes) via n8n webhooks
version: 0.1.0
license: MIT
"""

import requests
import json
import time
from pydantic import BaseModel, Field


class Tools:
    class Valves(BaseModel):
        n8n_base_url: str = Field(
            default="http://n8n:5678/webhook",
            description="URL de base des webhooks n8n"
        )

    def __init__(self):
        self.valves = self.Valves()

    def query_metrics(self, promql: str) -> str:
        """
        Interroge Prometheus avec une expression PromQL.
        Utiliser pour répondre aux questions sur les métriques : taux de requêtes,
        latences, CPU, mémoire, connexions PostgreSQL, services actifs.
        Exemples : up | rate(http_requests_total[5m]) | pg_stat_database_numbackends
        :param promql: Expression PromQL valide
        :return: Résultat formaté
        """
        try:
            resp = requests.post(
                f"{self.valves.n8n_base_url}/metrics",
                json={"query": promql},
                timeout=10,
            )
            data = resp.json()
            results = data.get("data", {}).get("result", [])
            if not results:
                return f"Aucun résultat pour : {promql}"
            lines = []
            for r in results[:10]:
                metric = r.get("metric", {})
                value = r.get("value", [None, "?"])[1]
                label = ", ".join(f"{k}={v}" for k, v in metric.items() if k != "__name__")
                name = metric.get("__name__", promql)
                lines.append(f"{name}{{{label}}} = {value}")
            return "\n".join(lines)
        except Exception as e:
            return f"Erreur Prometheus : {e}"

    def query_logs(self, logql: str, limit: int = 20) -> str:
        """
        Interroge Loki avec une expression LogQL pour récupérer des logs récents.
        Utiliser pour analyser les logs des services api, worker, postgres, etc.
        Exemples : {service="api"} | {service="worker"} |= "error"
        :param logql: Expression LogQL valide
        :param limit: Nombre maximum de lignes (défaut 20)
        :return: Lignes de log récentes
        """
        try:
            now_ns = int(time.time() * 1e9)
            start_ns = now_ns - int(3600 * 1e9)
            resp = requests.post(
                f"{self.valves.n8n_base_url}/logs",
                json={"query": logql, "limit": limit, "start": start_ns, "end": now_ns},
                timeout=10,
            )
            data = resp.json()
            streams = data.get("data", {}).get("result", [])
            if not streams:
                return f"Aucun log trouvé pour : {logql}"
            lines = []
            for stream in streams:
                svc = stream.get("stream", {}).get("service", "?")
                for _, msg in stream.get("values", [])[-limit:]:
                    try:
                        msg = json.loads(msg).get("message", msg)
                    except Exception:
                        pass
                    lines.append(f"[{svc}] {msg}")
            return "\n".join(lines[-limit:])
        except Exception as e:
            return f"Erreur Loki : {e}"

    def get_alerts(self) -> str:
        """
        Récupère les alertes actives depuis Alertmanager.
        Utiliser pour savoir si des incidents sont en cours sur la plateforme.
        :return: Liste des alertes actives avec leur sévérité
        """
        try:
            resp = requests.post(
                f"{self.valves.n8n_base_url}/alerts",
                json={},
                timeout=10,
            )
            alerts = resp.json()
            if not alerts:
                return "Aucune alerte active."
            lines = []
            for a in alerts:
                labels = a.get("labels", {})
                name = labels.get("alertname", "?")
                severity = labels.get("severity", "?")
                summary = a.get("annotations", {}).get("summary", "")
                lines.append(f"[{severity.upper()}] {name} — {summary}")
            return "\n".join(lines)
        except Exception as e:
            return f"Erreur Alertmanager : {e}"
