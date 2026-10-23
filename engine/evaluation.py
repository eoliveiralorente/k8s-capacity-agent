from collections import Counter
from config import CLUSTER, KUBERNETES_PROVIDER
from collectors.kubernetes import (
    get_cluster_events,
    get_nodes,
    get_pods,
)
from collectors.metrics import get_container_metrics, get_node_metrics, get_pod_metrics
from collectors.gke import get_node_pools

from analyzers.capacity import analyze_capacity
from analyzers.providers import detect_cloud
from analyzers.decision import evaluate_decision
from analyzers.gke_pools import merge_gke_pools
from analyzers.health import evaluate_health
from analyzers.recommendations import recommend_pool
from analyzers.stability import analyze_stability
from analyzers.scheduling import (
    analyze_scheduling,
    scheduling_recommendations,
    summarize_causes,
    summarize_namespaces,
    summarize_resources,
)

from engine.recommendations import enrich_recommendations
from tenant_context import current_cluster_name, current_cluster_provider


def count_running_pending_pods(pods):

    count = 0

    for pod in pods.get("items", []):

        phase = pod.get("status", {}).get("phase", "-")

        if phase in ("Running", "Pending"):
            count += 1

    return count


def collect_cluster_data():

    provider = current_cluster_provider.get() or KUBERNETES_PROVIDER
    nodes = get_nodes()
    pods = get_pods()
    events = get_cluster_events()
    node_metrics = get_node_metrics()
    pod_metrics = get_pod_metrics()
    container_metrics = get_container_metrics()
    node_pools = get_node_pools() if provider == "gke" else []

    return {
        "nodes": nodes,
        "pods": pods,
        "events": events,
        "node_metrics": node_metrics,
        "pod_metrics": pod_metrics,
        "container_metrics": container_metrics,
        "node_pools": node_pools,
    }


def workload_recommendations(pods, container_metrics):
    """Grava a amostra atual por container e gera rightsizing pelo histórico."""
    import logging

    from analyzers.workloads import collect_workloads, rightsizing_recommendations
    from approval.store import load_workload_samples, save_workload_samples

    try:
        samples, specs = collect_workloads(pods, container_metrics)
        if samples:
            save_workload_samples(samples)
        return rightsizing_recommendations(specs, load_workload_samples(days=14))
    except Exception as exc:  # rightsizing nunca deve derrubar a avaliação
        logging.getLogger("capacity-agent").warning("Rightsizing indisponível: %s", exc)
        return []


def evaluate_cluster(data=None):
    if data is None:
        data = collect_cluster_data()

    nodes = data["nodes"]
    pods = data["pods"]
    events = data["events"]
    node_metrics = data["node_metrics"]
    pod_metrics = data["pod_metrics"]
    node_pools = data["node_pools"]

    node_count = len(nodes.get("items", []))
    pod_count = len(pods.get("items", []))
    running_pending = count_running_pending_pods(pods)

    health = evaluate_health(
        node_count,
        running_pending,
        len(node_metrics),
        len(pod_metrics),
    )

    capacity = analyze_capacity(
        nodes,
        pods,
        node_metrics,
        pod_metrics,
    )

    capacity = merge_gke_pools(capacity, node_pools)

    capacity_recommendations = []

    for pool_name, pool_data in capacity.items():

        pool_recs = recommend_pool(
            pool_name,
            pool_data["capacity"],
            pool_data["metrics"],
        )

        if pool_data.get("control_plane"):
            # Nunca recomendar redução/expansão automática do control plane.
            pool_recs = [r for r in pool_recs if r.get("type") != "UNDERUTILIZED_POOL"]

        for rec in pool_recs:
            rec["source"] = "capacity"
            rec["pool"] = pool_name
            rec["metrics"] = pool_data["metrics"]
            rec["node_count"] = pool_data["capacity"]["node_count"]
            capacity_recommendations.append(rec)

    workload_recs = workload_recommendations(pods, data.get("container_metrics") or {})

    scheduling_findings = analyze_scheduling(pods, events)

    scheduling_recs = scheduling_recommendations(scheduling_findings)

    for rec in scheduling_recs:
        rec["source"] = "scheduling"

    all_recommendations = enrich_recommendations(
        capacity_recommendations + workload_recs + scheduling_recs,
        node_pools,
        capacity,
    )

    decision = evaluate_decision(
        health,
        all_recommendations,
        scheduling_findings,
    )

    pending_pods = len({
        (item["namespace"], item["pod"])
        for item in scheduling_findings
    })

    cloud, cloud_counts = detect_cloud(nodes)

    summary = {
        "cloud": cloud,
        "cloud_nodes": cloud_counts,
        "nodes": node_count,
        "pods": pod_count,
        "running_pending_pods": running_pending,
        "node_pools": len(node_pools) or len(capacity),
        "node_metrics": len(node_metrics),
        "pod_metrics": len(pod_metrics),
        "pending_pods": pending_pods,
        "scheduling_issues": len(scheduling_findings),
        "recommendations_count": len(all_recommendations),
    }

    scheduling_summary = {
        "causes": dict(summarize_causes(scheduling_findings)),
        "namespaces": {
            ns: dict(counter)
            for ns, counter in summarize_namespaces(
                scheduling_findings
            ).items()
        },
    }

    stability = analyze_stability(
        capacity,
        scheduling_summary,
        summary,
    )

    return {
        "summary": summary,
        "health": health,
        "capacity": capacity,
        "stability": stability,
        "scheduling": {
            "findings": scheduling_findings,
            "causes": scheduling_summary["causes"],
            "namespaces": scheduling_summary["namespaces"],
            "resources": {
                f"{rtype}/{rname}": count
                for (rtype, rname), count in summarize_resources(
                    scheduling_findings
                ).items()
            },
        },
        "recommendations": all_recommendations,
        "decision": decision,
        "node_pools": node_pools,
    }


def summarize_report_for_api(report):

    namespaces = report.get("scheduling", {}).get("namespaces", {})
    top_namespaces = dict(
        sorted(
            namespaces.items(),
            key=lambda item: sum(item[1].values()),
            reverse=True,
        )[:15]
    )

    findings = report.get("scheduling", {}).get("findings", [])

    seen = set()
    top_findings = []

    for finding in findings:
        key = (finding["namespace"], finding["pod"])
        if key in seen:
            continue
        seen.add(key)
        top_findings.append(finding)
        if len(top_findings) >= 30:
            break

    findings_by_namespace = {}

    for finding in findings:
        ns = finding["namespace"]
        if ns not in findings_by_namespace:
            findings_by_namespace[ns] = []

        pod_key = finding["pod"]
        existing_pods = {f["pod"] for f in findings_by_namespace[ns]}

        if pod_key not in existing_pods:
            findings_by_namespace[ns].append(finding)

    for ns in findings_by_namespace:
        findings_by_namespace[ns].sort(
            key=lambda f: (
                {"HIGH": 0, "MEDIUM": 1, "LOW": 2}.get(f.get("severity"), 9),
                f.get("pod", ""),
            )
        )

    stability = ensure_stability(report)

    return {
        "evaluation_id": report.get("evaluation_id"),
        "cluster": report.get("cluster"),
        "created_at": report.get("created_at"),
        "summary": report.get("summary"),
        "health": report.get("health"),
        "decision": report.get("decision"),
        "capacity": report.get("capacity"),
        "scheduling": {
            "causes": report.get("scheduling", {}).get("causes", {}),
            "namespaces": top_namespaces,
            "resources": report.get("scheduling", {}).get("resources", {}),
            "top_findings": top_findings,
            "findings_by_namespace": findings_by_namespace,
        },
        "recommendations": report.get("recommendations", []),
        "stability": stability,
    }


CARRY_FIELDS = (
    "status", "approved_by", "approved_at",
    "rejected_by", "rejected_at", "rejection_reason",
)


def carry_over_decisions(previous_items, new_items):
    """Mantém decisões humanas entre avaliações.

    - Rejeitada continua rejeitada (mesmo id = mesma recomendação).
    - Aprovada só continua aprovada se a operação proposta for idêntica;
      se os parâmetros mudaram, volta a exigir nova aprovação.
    - Executada/falhou: a situação reapareceu, então volta para pendente.
    """
    previous = {item["id"]: item for item in previous_items or []}
    carried = 0
    for item in new_items:
        old = previous.get(item["id"])
        if not old:
            continue
        status = old.get("status")
        same_operation = old.get("operation", {}).get("params") == item.get("operation", {}).get("params")
        if status == "rejected" or (status == "approved" and same_operation):
            for field in CARRY_FIELDS:
                item[field] = old.get(field)
            carried += 1
    return carried


REDUCTION_MAX_CPU_PEAK_PCT = 50
REDUCTION_MAX_MEM_PEAK_PCT = 70


def apply_history(recommendations, history):
    """Anexa histórico/confiança e suprime reduções contraditas por picos."""
    from analyzers.history import describe

    kept, suppressed = [], []
    for rec in recommendations:
        pool_history = history.get(rec.get("pool")) if rec.get("pool") else None
        rec["history"] = pool_history
        if pool_history or not rec.get("confidence"):
            rec["confidence"] = pool_history["confidence"] if pool_history else "baixa"
        if pool_history:
            rec["action"] = f"{rec.get('action', '')} ({describe(pool_history)})"
        if rec.get("type") == "UNDERUTILIZED_POOL" and pool_history:
            cpu_peak = pool_history.get("cpu_usage_max") or 0
            mem_peak = pool_history.get("mem_usage_max") or 0
            if cpu_peak > REDUCTION_MAX_CPU_PEAK_PCT or mem_peak > REDUCTION_MAX_MEM_PEAK_PCT:
                suppressed.append({
                    "id": rec["id"], "pool": rec["pool"], "type": rec["type"],
                    "reason": f"Picos históricos (CPU {cpu_peak}%, memória {mem_peak}%) não permitem redução",
                })
                continue
        kept.append(rec)
    return kept, suppressed


def run_evaluation(source="cli", actor=None):

    from datetime import datetime, timezone

    from analyzers.history import summarize_history
    from approval.store import (
        append_audit,
        load_metric_samples,
        load_recommendations,
        save_metric_samples,
        save_recommendations,
        save_report,
    )
    from config import CLUSTER
    from collectors.kubernetes import get_current_context
    from engine.recommendations import new_evaluation_id

    result = evaluate_cluster()
    provider = current_cluster_provider.get() or KUBERNETES_PROVIDER
    cluster = (
        get_current_context()
        if provider != "gke"
        else current_cluster_name.get() or CLUSTER
    )
    evaluation_id = new_evaluation_id()

    save_metric_samples(result["capacity"])
    history = summarize_history(load_metric_samples(days=14))
    result["history"] = history
    result["recommendations"], result["suppressed_recommendations"] = apply_history(
        result["recommendations"], history
    )
    result["summary"]["recommendations_count"] = len(result["recommendations"])

    report = {
        "evaluation_id": evaluation_id,
        "cluster": cluster,
        "created_at": datetime.now(timezone.utc).isoformat(),
        **result,
    }

    carried = carry_over_decisions(
        load_recommendations().get("items", []),
        result["recommendations"],
    )

    save_report(evaluation_id, report)
    save_recommendations(evaluation_id, result["recommendations"])

    append_audit("evaluate", {
        "evaluation_id": evaluation_id,
        "recommendations": len(result["recommendations"]),
        "decision_allowed": result["decision"]["allowed"],
        "source": source,
        "by": actor,
        "decisions_kept": carried,
    })

    return report


def ensure_stability(report):

    stability = report.get("stability")

    if stability:
        return stability

    if not report.get("capacity"):
        return None

    scheduling_raw = report.get("scheduling", {})

    return analyze_stability(
        report.get("capacity", {}),
        {
            "causes": scheduling_raw.get("causes", {}),
            "namespaces": scheduling_raw.get("namespaces", {}),
        },
        report.get("summary", {}),
    )
