"""Amostrador periódico de métricas (histórico sem Prometheus).

A cada CAPACITY_AGENT_SAMPLE_MINUTES (padrão 15; 0 desativa), coleta nodes,
pods e `kubectl top` de cada cluster cadastrado e grava uma amostra por pool.
Não cria relatório nem recomendações e não altera o cluster (somente leitura).
"""
import logging
import os
import threading

from tenant_context import current_cluster_id, current_cluster_name, current_tenant_id

log = logging.getLogger("capacity-agent.sampler")

SAMPLE_MINUTES = int(os.getenv("CAPACITY_AGENT_SAMPLE_MINUTES", "15") or 0)

_stop = threading.Event()
_thread = None


def sample_cluster(tenant_id, cluster_id, cluster_name=None):
    from analyzers.capacity import analyze_capacity
    from approval.store import save_metric_samples
    from collectors.kubernetes import get_nodes, get_pods
    from analyzers.workloads import collect_workloads
    from approval.store import save_workload_samples
    from collectors.metrics import get_container_metrics, get_node_metrics, get_pod_metrics

    tokens = [
        (current_tenant_id, current_tenant_id.set(tenant_id)),
        (current_cluster_id, current_cluster_id.set(cluster_id)),
        (current_cluster_name, current_cluster_name.set(cluster_name)),
    ]
    try:
        node_metrics = get_node_metrics()
        if not node_metrics:
            log.warning("Sem métricas de nodes (metrics-server?) no cluster %s", cluster_name or cluster_id)
            return False
        pods = get_pods()
        capacity = analyze_capacity(get_nodes(), pods, node_metrics, get_pod_metrics())
        save_metric_samples(capacity)
        workload_samples, _ = collect_workloads(pods, get_container_metrics())
        if workload_samples:
            save_workload_samples(workload_samples)
        return True
    finally:
        for var, token in reversed(tokens):
            var.reset(token)


def sample_all():
    from accounts.store import list_all_clusters

    for cluster in list_all_clusters():
        if _stop.is_set():
            return
        if cluster.get("mode") == "agent":
            continue  # o coletor in-cluster envia as próprias amostras
        try:
            sample_cluster(cluster["tenant_id"], cluster["id"], cluster["name"])
        except Exception as exc:  # um cluster com falha não interrompe os outros
            log.warning("Falha ao amostrar cluster %s: %s", cluster.get("name"), exc)


def _loop():
    while not _stop.wait(SAMPLE_MINUTES * 60):
        sample_all()


def start():
    global _thread
    if SAMPLE_MINUTES <= 0 or (_thread and _thread.is_alive()):
        return
    _stop.clear()
    _thread = threading.Thread(target=_loop, name="metric-sampler", daemon=True)
    _thread.start()
    log.info("Amostrador de métricas ativo a cada %s min", SAMPLE_MINUTES)


def stop():
    _stop.set()
