"""Execução simulada para o ambiente de demonstração.

No cluster demo (snapshot marcado com "demo": true) as recomendações continuam
executáveis no painel, para mostrar o fluxo Aprovar → Simular → Executar, mas
nada chama o kubectl: o resultado é montado a partir da própria operação.
"""
import json

KINDS = {"Deployment": "deployment", "StatefulSet": "statefulset", "DaemonSet": "daemonset"}
NOTE = "[demo] Simulado: nenhum cluster real foi alterado."


def is_demo_cluster():
    from tenant_context import current_cluster_mode

    if current_cluster_mode.get() != "agent":
        return False
    try:
        from approval.store import load_cluster_snapshot

        snapshot = load_cluster_snapshot()
    except Exception:
        return False
    return bool(snapshot and snapshot.get("demo"))


def _command(kind, p, dry_run):
    ns = p.get("namespace", "default")
    workload = f"{KINDS.get(p.get('kind'), 'deployment')}/{p.get('name', '')}"
    suffix = " --dry-run=server" if dry_run else ""
    if kind == "k8s_set_resources":
        t = p.get("target", {})
        return (f"kubectl set resources {workload} --namespace {ns} --containers {p.get('container')} "
                f"--requests=cpu={t.get('cpu')},memory={t.get('memory')}{suffix}",
                f"{workload.replace('deployment/', 'deployment.apps/').replace('statefulset/', 'statefulset.apps/')} resource requirements updated")
    if kind == "k8s_scale":
        return (f"kubectl scale {workload} --namespace {ns} --replicas={p.get('target_replicas')}{suffix}",
                f"{workload.replace('deployment/', 'deployment.apps/').replace('statefulset/', 'statefulset.apps/')} scaled")
    if kind == "k8s_create_hpa":
        return (f"kubectl autoscale {workload} --namespace {ns} --min={p.get('min_replicas')} "
                f"--max={p.get('max_replicas')} --cpu-percent={p.get('cpu_percent')}{suffix}",
                f"horizontalpodautoscaler.autoscaling/{p.get('name')} autoscaled")
    if kind == "k8s_patch_hpa_max":
        patch = json.dumps({"spec": {"maxReplicas": p.get("target_max")}})
        return (f"kubectl patch hpa {p.get('hpa')} --namespace {ns} -p '{patch}'{suffix}",
                f"horizontalpodautoscaler.autoscaling/{p.get('hpa')} patched")
    if kind == "scale_node_pool":
        return (f"# node pool {p.get('pool', p.get('node_pool', ''))}: {p.get('current_nodes', '?')} → "
                f"{p.get('target_nodes', '?')} nodes (provedor de cloud)",
                "node pool redimensionado")
    return (f"# operação {kind}", "operação aplicada")


def _rollback(kind, p):
    ns = p.get("namespace", "default")
    workload = f"{KINDS.get(p.get('kind'), 'deployment')}/{p.get('name', '')}"
    cur = p.get("current") or {}
    if kind == "k8s_set_resources" and cur.get("cpu") and cur.get("memory"):
        return (f"kubectl set resources {workload} --namespace {ns} --containers {p.get('container')} "
                f"--requests=cpu={cur['cpu']},memory={cur['memory']}")
    if kind == "k8s_scale" and p.get("current_replicas"):
        return f"kubectl scale {workload} --namespace {ns} --replicas={p['current_replicas']}"
    if kind == "k8s_create_hpa":
        return f"kubectl delete hpa {p.get('name')} --namespace {ns}"
    if kind == "k8s_patch_hpa_max" and p.get("current_max"):
        return f"kubectl patch hpa {p.get('hpa')} --namespace {ns} -p '{{\"spec\":{{\"maxReplicas\":{p['current_max']}}}}}'"
    return None


def simulate_operation(operation, dry_run=False):
    kind = operation.get("kind")
    params = operation.get("params") or {}
    command, result = _command(kind, params, dry_run)
    if dry_run:
        output = f"Validado pelo cluster (dry-run): {result} (server dry run)\n{NOTE}"
    else:
        output = f"{result}\n{NOTE}"
    response = {"success": True, "dry_run": dry_run, "returncode": 0, "output": output,
                "command": command, "simulated": True}
    rollback = _rollback(kind, params)
    if rollback:
        response["rollback_command"] = rollback
    return response
