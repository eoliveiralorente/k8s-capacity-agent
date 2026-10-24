"""Snapshot do cluster para o modo agente (coletor in-cluster → painel).

O coletor roda dentro do cluster do cliente com ServiceAccount somente leitura,
monta um snapshot e envia ao painel por HTTPS (conexão só de saída).
"""
import gzip
import json
import logging
import os
import random
import ssl
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

SNAPSHOT_VERSION = 1
MAX_SNAPSHOT_BYTES = 50 * 1024 * 1024  # descomprimido
LAST_APPLIED = "kubectl.kubernetes.io/last-applied-configuration"

log = logging.getLogger("capacity-agent.collector")


def _slim(items):
    """Remove campos volumosos e inúteis para a análise (managedFields etc.)."""
    for item in items:
        metadata = item.get("metadata", {})
        metadata.pop("managedFields", None)
        annotations = metadata.get("annotations")
        if annotations:
            annotations.pop(LAST_APPLIED, None)
    return items


def build_snapshot():
    from collectors.kubernetes import get_cluster_events, get_nodes, get_pods
    from collectors.metrics import get_container_metrics, get_node_metrics, get_pod_metrics

    nodes = get_nodes()
    pods = get_pods()
    events = get_cluster_events()
    return {
        "version": SNAPSHOT_VERSION,
        "collected_at": datetime.now(timezone.utc).isoformat(),
        "nodes": {"items": _slim(nodes.get("items", []))},
        "pods": {"items": _slim(pods.get("items", []))},
        "events": {"items": _slim(events.get("items", []))},
        "node_metrics": get_node_metrics(),
        "pod_metrics": get_pod_metrics(),
        "container_metrics": [
            [ns, pod, container, value["cpu_m"], value["mem_b"]]
            for (ns, pod, container), value in get_container_metrics().items()
        ],
    }


def snapshot_to_data(snapshot):
    """Converte o snapshot recebido no formato usado por evaluate_cluster."""
    return {
        "nodes": snapshot.get("nodes") or {"items": []},
        "pods": snapshot.get("pods") or {"items": []},
        "events": snapshot.get("events") or {"items": []},
        "node_metrics": snapshot.get("node_metrics") or {},
        "pod_metrics": snapshot.get("pod_metrics") or {},
        "container_metrics": {
            (row[0], row[1], row[2]): {"cpu_m": int(row[3]), "mem_b": int(row[4])}
            for row in snapshot.get("container_metrics") or []
            if isinstance(row, list) and len(row) == 5
        },
        "node_pools": [],
    }


def validate_snapshot(snapshot):
    if not isinstance(snapshot, dict) or snapshot.get("version") != SNAPSHOT_VERSION:
        raise ValueError("Versão de snapshot não suportada; atualize o coletor")
    for key in ("nodes", "pods", "events"):
        if not isinstance(snapshot.get(key), dict) or not isinstance(snapshot[key].get("items"), list):
            raise ValueError(f"Snapshot inválido: campo '{key}'")
    for key in ("node_metrics", "pod_metrics"):
        if not isinstance(snapshot.get(key), dict):
            raise ValueError(f"Snapshot inválido: campo '{key}'")
    if not isinstance(snapshot.get("container_metrics"), list):
        raise ValueError("Snapshot inválido: campo 'container_metrics'")


def send_snapshot(panel_url, token, snapshot, timeout=60):
    body = gzip.compress(json.dumps(snapshot, ensure_ascii=False).encode("utf-8"))
    request = urllib.request.Request(
        panel_url.rstrip("/") + "/api/ingest",
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Content-Encoding": "gzip",
            "User-Agent": "capacity-collector/1",
        },
    )
    context = ssl.create_default_context(cafile=os.getenv("CAPACITY_AGENT_CA_FILE") or None)
    with urllib.request.urlopen(request, timeout=timeout, context=context) as response:
        return response.status, json.loads(response.read() or b"{}")


def run_collector(panel_url, token, interval_seconds=900, once=False):
    """Loop do coletor: coleta, envia, espera. Falhas são registradas e repetidas."""
    if not panel_url or not token:
        raise SystemExit("Defina CAPACITY_AGENT_PANEL_URL e CAPACITY_AGENT_INGEST_TOKEN")
    if panel_url.startswith("http://") and not os.getenv("CAPACITY_AGENT_ALLOW_HTTP"):
        host = panel_url.split("://", 1)[1].split("/", 1)[0].split(":")[0]
        if host not in {"localhost", "127.0.0.1", "host.docker.internal"} and not host.endswith(".svc") \
                and ".svc." not in host:
            raise SystemExit("Use HTTPS no painel (ou CAPACITY_AGENT_ALLOW_HTTP=1 só para teste)")

    failures = 0
    while True:
        try:
            snapshot = build_snapshot()
            status, payload = send_snapshot(panel_url, token, snapshot)
            failures = 0
            log.info(
                "Snapshot enviado: %s nodes, %s pods (HTTP %s)",
                len(snapshot["nodes"]["items"]), len(snapshot["pods"]["items"]), status,
            )
            print(f"[collector] enviado: {len(snapshot['nodes']['items'])} nodes, "
                  f"{len(snapshot['pods']['items'])} pods — HTTP {status} {payload.get('detail', '')}", flush=True)
        except urllib.error.HTTPError as exc:
            failures += 1
            detail = exc.read().decode("utf-8", "replace")[:300]
            print(f"[collector] painel recusou (HTTP {exc.code}): {detail}", flush=True)
            if exc.code in (401, 403):
                print("[collector] token inválido ou revogado — gere um novo no painel", flush=True)
        except Exception as exc:  # rede, kubectl, etc.
            failures += 1
            print(f"[collector] falha: {exc}", flush=True)

        if once:
            return 0 if failures == 0 else 1

        # Backoff exponencial em falhas (máx. 15 min), com jitter para não sincronizar coletores.
        wait = interval_seconds if failures == 0 else min(900, 30 * 2 ** min(failures, 5))
        time.sleep(wait + random.uniform(0, 10))
