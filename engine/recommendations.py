import hashlib
import uuid
from datetime import datetime, timezone

from config import CLUSTER, KUBERNETES_PROVIDER, PROJECT, REGION, REQUIRE_APPROVAL
from tenant_context import current_cluster_provider, current_tenant_id


EXECUTABLE_TYPES = {
    "CPU_PRESSURE",
    "MEMORY_PRESSURE",
    "SCHEDULING_CPU",
    "SCHEDULING_MEMORY",
    "CLUSTER_AUTOSCALER",
    "UNDERUTILIZED_POOL",
}


def _stable_id(source, rec_type, pool=None):

    key = f"{source}:{rec_type}:{pool or 'global'}"

    return hashlib.sha256(key.encode()).hexdigest()[:12]


def _scale_operation(pool_name, current_nodes, direction, delta=1):

    if direction == "up":
        target = current_nodes + delta
    else:
        target = max(1, current_nodes - delta)

    args = [
        "gcloud", "container", "clusters", "resize", CLUSTER,
        "--node-pool", str(pool_name),
        "--num-nodes", str(target),
        "--region", REGION,
        "--project", PROJECT,
        "--quiet",
    ]
    command = " ".join(args)

    return {
        "kind": "scale_node_pool",
        "executable": True,
        "params": {
            "pool": pool_name,
            "current_nodes": current_nodes,
            "target_nodes": target,
            "direction": direction,
        },
        "dry_run_command": f"# preview: {command}",
        "execute_command": command,
        "execute_args": args,
        "target": {"cluster": CLUSTER, "region": REGION, "project": PROJECT},
    }


def _manual_operation(reason):

    return {
        "kind": "manual_review",
        "executable": False,
        "params": {"reason": reason},
        "dry_run_command": None,
        "execute_command": None,
    }


def _build_operation(rec, node_pools):

    rec_type = rec.get("type", "UNKNOWN")
    pool_name = rec.get("pool")
    node_count = rec.get("node_count", 0)

    if not pool_name and node_pools:
        pool_name = node_pools[0].get("name")
        node_count = node_pools[0].get("initialNodeCount", 0)

    if rec_type in ("CPU_PRESSURE", "SCHEDULING_CPU", "CLUSTER_AUTOSCALER"):
        if pool_name and node_count:
            return _scale_operation(pool_name, node_count, "up")
        return _manual_operation("Pool não identificado para scale-up")

    if rec_type in ("MEMORY_PRESSURE", "SCHEDULING_MEMORY"):
        if pool_name and node_count:
            return _scale_operation(pool_name, node_count, "up")
        return _manual_operation("Pool não identificado para scale-up")

    if rec_type == "UNDERUTILIZED_POOL":
        if pool_name and node_count > 1:
            return _scale_operation(pool_name, node_count, "down")
        return _manual_operation("Redução não recomendada com 1 node")

    return _manual_operation(
        "Ação requer intervenção manual do time DevOps"
    )


def enrich_recommendations(recommendations, node_pools, capacity=None):

    pool_lookup = {}
    capacity = capacity or {}

    for pool in node_pools:
        name = pool.get("name")
        configured = pool.get("initialNodeCount") or 0
        actual = capacity.get(name, {}).get("capacity", {}).get("node_count", 0)
        pool_lookup[name] = actual or configured

    enriched = []

    for rec in recommendations:

        pool_name = rec.get("pool")

        if pool_name and pool_name in pool_lookup:
            rec.setdefault("node_count", pool_lookup[pool_name])

        provider = current_cluster_provider.get() or KUBERNETES_PROVIDER
        if rec.get("operation"):
            operation = rec["operation"]  # ação já definida pelo analisador (ex.: workload)
        elif current_tenant_id.get():
            # Modo multiempresa: o cluster do cliente não tem projeto/região GKE
            # cadastrados; usar o config global alteraria o cluster errado.
            operation = _manual_operation(
                "Execução automática desabilitada no modo multiempresa "
                "até o cluster ter coordenadas GKE próprias"
            )
        elif provider == "gke" and CLUSTER and REGION and PROJECT:
            operation = _build_operation(rec, node_pools)
        else:
            operation = _manual_operation("Escalonamento automático disponível apenas no modo GKE configurado")
        rec_type = rec.get("type", "UNKNOWN")
        source = rec.get("source", "unknown")

        enriched.append({
            "id": _stable_id(source, rec_type, pool_name),
            "source": source,
            "type": rec_type,
            "severity": rec.get("severity", "MEDIUM"),
            "pool": pool_name,
            "message": rec.get("message", rec.get("action", "")),
            "action": rec.get("action", ""),
            "affected_pods": rec.get("affected_pods", 0),
            "metrics": rec.get("metrics"),
            "operation": operation,
            "confidence": rec.get("confidence"),
            "requires_approval": REQUIRE_APPROVAL or rec_type in EXECUTABLE_TYPES,
            "auto_execute": False,
            "status": "pending",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "approved_by": None,
            "approved_at": None,
            "rejected_by": None,
            "rejected_at": None,
            "executed_at": None,
            "execution_result": None,
        })

    severity_order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}

    enriched.sort(
        key=lambda x: (
            severity_order.get(x["severity"], 9),
            -x.get("affected_pods", 0),
        )
    )

    return enriched


def new_evaluation_id():

    return str(uuid.uuid4())
