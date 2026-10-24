"""Ambiente de demonstração com dados 100% fictícios.

Cria (ou reaproveita) a empresa "Nimbus Pay (demo)" com o cluster
"prod-pagamentos", gera um snapshot realista e 7 dias de histórico, roda a
avaliação e semeia custos e o diário de bordo. Nada disso toca um cluster real:
o cluster é do tipo agente (somente leitura) e marcado como demo.

Uso:  python agent.py demo [--email demo@exemplo.com] [--password ...]
"""
import copy
import math
import random
import secrets
from datetime import datetime, timedelta, timezone

GI = 1024 ** 3
MI = 1024 ** 2
DEMO_COMPANY = "Nimbus Pay (demo)"
DEMO_CLUSTER = "prod-pagamentos"
POOL_LABEL = "node-pool"

NODES = [
    # nome, pool, vCPU, memória GiB, control plane
    ("cp-1", "control-plane", 4, 8, True),
    ("general-a1", "general", 8, 32, False),
    ("general-a2", "general", 8, 32, False),
    ("general-a3", "general", 8, 32, False),
    ("memory-b1", "memory", 8, 64, False),
    ("memory-b2", "memory", 8, 64, False),
]

# namespace, nome, tipo, réplicas, pool, cpu_req m, mem_req Mi, cpu_uso m, mem_uso Mi, perfil
WORKLOADS = [
    ("payments", "api", "Deployment", 4, "general", 1000, 1024, 110, 380, "diurno"),
    ("payments", "worker", "Deployment", 3, "general", 500, 512, 430, 400, "constante"),
    ("checkout", "web", "Deployment", 3, "general", 250, 256, 60, 180, "pico"),
    ("catalog", "search", "Deployment", 6, "general", 500, 1024, 35, 210, "diurno"),
    ("notifications", "sender", "Deployment", 5, "general", 200, 256, 185, 190, "constante"),
    ("ingress-nginx", "controller", "Deployment", 2, "general", 200, 256, 90, 210, "diurno"),
    ("monitoring", "grafana", "Deployment", 1, "general", 0, 0, 40, 300, "constante"),
    ("data", "redis", "StatefulSet", 1, "memory", 500, 2048, 120, 1990, "constante"),
    ("data", "postgres", "StatefulSet", 1, "memory", 2000, 8192, 1100, 6100, "diurno"),
    ("data", "kafka", "StatefulSet", 3, "memory", 1500, 12288, 1050, 11000, "constante"),
    ("analytics", "spark-driver", "Deployment", 2, "memory", 2000, 16384, 1400, 15800, "diurno"),
    ("kube-system", "coredns", "Deployment", 2, "general", 100, 70, 8, 30, "constante"),
    ("kube-system", "metrics-server", "Deployment", 1, "general", 100, 200, 6, 40, "constante"),
]
HPAS = [("notifications", "sender", 2, 5)]           # namespace, alvo, min, max (no limite)
CRASHLOOP = ("reports", "pdf-exporter")               # 1 pod em CrashLoopBackOff
PENDING = ("batch", "etl-noturno", 2, 40960)          # 2 pods pedindo 40 GiB: não cabem


def _ts(dt):
    return dt.isoformat()


def _rand_hash(rng, n=10):
    return "".join(rng.choice("bcdfghjklmnpqrstvwxz2456789") for _ in range(n))


def _factor(profile, hour, rng):
    """Multiplicador de uso por hora do dia (horário de Brasília)."""
    daily = 0.65 + 0.55 * max(0.0, math.sin((hour - 6) / 24 * 2 * math.pi))
    if profile == "constante":
        base = 0.92 + 0.08 * daily
    elif profile == "pico":
        base = 0.6 + 0.4 * daily
        if hour in (12, 13, 19, 20, 21):
            base *= 3.4  # pico de almoço e noite no checkout
    else:
        base = daily
    return max(0.05, base * rng.uniform(0.9, 1.1))


def build_snapshot(now=None, seed=7):
    rng = random.Random(seed)
    now = now or datetime.now(timezone.utc)
    hour_local = (now.hour - 3) % 24

    nodes, pods, events, controllers, hpas = [], [], [], [], []
    node_use = {n[0]: [0, 0] for n in NODES}
    pod_metrics, container_metrics = {}, []

    for name, pool, cpu, mem, cp in NODES:
        labels = {"kubernetes.io/hostname": name, POOL_LABEL: pool, "topology.kubernetes.io/zone": "sa-east-1a"}
        if cp:
            labels["node-role.kubernetes.io/control-plane"] = ""
        nodes.append({
            "metadata": {"name": name, "labels": labels},
            "spec": {"providerID": f"demo://{name}",
                     **({"taints": [{"key": "node-role.kubernetes.io/control-plane", "effect": "NoSchedule"}]} if cp else {})},
            "status": {
                "allocatable": {"cpu": str(cpu), "memory": f"{mem * 1024 - 900}Mi", "pods": "110"},
                "capacity": {"cpu": str(cpu), "memory": f"{mem * 1024}Mi", "pods": "110"},
                "conditions": [{"type": "Ready", "status": "True"},
                               {"type": "MemoryPressure", "status": "False"}],
                "nodeInfo": {"kubeletVersion": "v1.30.4", "containerRuntimeVersion": "containerd://1.7.20"},
            },
        })

    pool_nodes = {}
    for name, pool, *_ in NODES:
        pool_nodes.setdefault(pool, []).append(name)

    def add_pod(ns, pod_name, node, owner, cname, cpu_req, mem_req, cpu_use, mem_use, phase="Running",
                waiting=None, restarts=0, labels=None):
        resources = {}
        if cpu_req or mem_req:
            resources = {"requests": {"cpu": f"{cpu_req}m", "memory": f"{mem_req}Mi"},
                         "limits": {"memory": f"{mem_req * 2}Mi"}}
        status = {"phase": phase, "qosClass": "Burstable" if resources else "BestEffort"}
        if phase == "Running":
            state = {"waiting": {"reason": waiting}} if waiting else {"running": {"startedAt": _ts(now - timedelta(days=3))}}
            status["containerStatuses"] = [{"name": cname, "ready": not waiting, "restartCount": restarts, "state": state}]
        else:
            status["conditions"] = [{"type": "PodScheduled", "status": "False", "reason": "Unschedulable"}]
        pods.append({
            "metadata": {"name": pod_name, "namespace": ns, "labels": labels or {}, "ownerReferences": [owner]},
            "spec": {**({"nodeName": node} if node else {}), "containers": [{"name": cname, "resources": resources}]},
            "status": status,
        })
        if phase == "Running" and node:
            pod_metrics[f"{ns}/{pod_name}"] = {"cpu_m": cpu_use, "mem_b": mem_use * MI}
            container_metrics.append([ns, pod_name, cname, cpu_use, mem_use * MI])
            node_use[node][0] += cpu_use
            node_use[node][1] += mem_use * MI

    for ns, name, kind, replicas, pool, cpu_req, mem_req, cpu_use, mem_use, profile in WORKLOADS:
        meta = {"name": name, "namespace": ns, "labels": {"app": name}}
        controllers.append({"kind": kind, "metadata": meta, "spec": {"replicas": replicas},
                            "status": {"replicas": replicas, "readyReplicas": replicas}})
        rs_hash = _rand_hash(rng)
        factor = _factor(profile, hour_local, rng)
        for i in range(replicas):
            node = pool_nodes[pool][i % len(pool_nodes[pool])]
            if kind == "Deployment":
                pod_name = f"{name}-{rs_hash}-{_rand_hash(rng, 5)}"
                owner = {"kind": "ReplicaSet", "name": f"{name}-{rs_hash}"}
                labels = {"app": name, "pod-template-hash": rs_hash}
            else:
                pod_name = f"{name}-{i}"
                owner = {"kind": "StatefulSet", "name": name}
                labels = {"app": name}
            jitter = rng.uniform(0.92, 1.08)
            add_pod(ns, pod_name, node, owner, name, cpu_req, mem_req,
                    max(1, int(cpu_use * factor * jitter)), int(mem_use * jitter if mem_use > 1000 else mem_use * jitter),
                    labels=labels)

    # kube-proxy em todos os nodes
    controllers.append({"kind": "DaemonSet", "metadata": {"name": "kube-proxy", "namespace": "kube-system"}, "spec": {}})
    for name, *_ in NODES:
        add_pod("kube-system", f"kube-proxy-{_rand_hash(rng, 5)}", name, {"kind": "DaemonSet", "name": "kube-proxy"},
                "kube-proxy", 50, 64, 4, 28)

    for ns, target, min_r, max_r in HPAS:
        hpas.append({"metadata": {"name": target, "namespace": ns},
                     "spec": {"scaleTargetRef": {"kind": "Deployment", "name": target},
                              "minReplicas": min_r, "maxReplicas": max_r,
                              "metrics": [{"type": "Resource", "resource": {"name": "cpu", "target": {"type": "Utilization", "averageUtilization": 70}}}]},
                     "status": {"currentReplicas": max_r, "desiredReplicas": max_r}})

    ns, name = CRASHLOOP
    controllers.append({"kind": "Deployment", "metadata": {"name": name, "namespace": ns}, "spec": {"replicas": 1}})
    h = _rand_hash(rng)
    add_pod(ns, f"{name}-{h}-{_rand_hash(rng, 5)}", "general-a2", {"kind": "ReplicaSet", "name": f"{name}-{h}"},
            name, 200, 256, 0, 0, waiting="CrashLoopBackOff", restarts=23, labels={"pod-template-hash": h})

    ns, name, count, mem_req = PENDING
    controllers.append({"kind": "Deployment", "metadata": {"name": name, "namespace": ns}, "spec": {"replicas": count}})
    h = _rand_hash(rng)
    for _ in range(count):
        pod_name = f"{name}-{h}-{_rand_hash(rng, 5)}"
        add_pod(ns, pod_name, None, {"kind": "ReplicaSet", "name": f"{name}-{h}"}, name, 2000, mem_req, 0, 0,
                phase="Pending", labels={"pod-template-hash": h})
        events.append({
            "metadata": {"name": f"{pod_name}.evt", "namespace": ns},
            "type": "Warning", "reason": "FailedScheduling", "count": 48,
            "involvedObject": {"kind": "Pod", "name": pod_name, "namespace": ns},
            "message": "0/6 nodes are available: 1 node(s) had untolerated taint {node-role.kubernetes.io/control-plane: }, "
                       "5 Insufficient memory. preemption: 0/6 nodes are available: 1 Preemption is not helpful for "
                       "scheduling, 5 No preemption victims found for incoming pod.",
            "firstTimestamp": _ts(now - timedelta(hours=9)), "lastTimestamp": _ts(now - timedelta(minutes=4)),
        })

    node_metrics = {}
    for name, pool, cpu, mem, cp in NODES:
        used_cpu = node_use[name][0] + (350 if cp else 180)
        used_mem = node_use[name][1] + (1800 if cp else 900) * MI
        node_metrics[name] = {"cpu": f"{used_cpu}m", "cpu_pct": f"{round(used_cpu / (cpu * 10))}%",
                              "mem": f"{used_mem // MI}Mi", "mem_pct": f"{round(used_mem / (mem * GI) * 100)}%"}

    return {
        "version": 1, "demo": True, "collected_at": _ts(now),
        "nodes": {"items": nodes}, "pods": {"items": pods}, "events": {"items": events},
        "node_metrics": node_metrics, "pod_metrics": pod_metrics,
        "controllers": {"items": controllers}, "hpas": {"items": hpas},
        "container_metrics": container_metrics,
    }


def _ensure_account(email, password):
    from accounts.store import DuplicateAccountError, _connect, initialize_database, register_account

    initialize_database()
    try:
        user = register_account(DEMO_COMPANY, "Equipe Demo", email, password)
        return user["tenant_id"], True
    except DuplicateAccountError:
        with _connect() as connection:
            row = connection.execute("SELECT tenant_id FROM users WHERE email = ?", (email.strip().lower(),)).fetchone()
        return row["tenant_id"], False


def _ensure_cluster(tenant_id):
    from accounts.store import create_agent_cluster, list_clusters

    for cluster in list_clusters(tenant_id):
        if cluster["name"] == DEMO_CLUSTER:
            return cluster
    cluster, _token = create_agent_cluster(tenant_id, DEMO_CLUSTER)
    return cluster


def _clear_cluster_state(tenant_id, cluster_id):
    from approval import store

    with store._transaction(write=True) as connection:
        for table in ("metric_samples", "workload_samples"):
            connection.execute(f"DELETE FROM {table} WHERE tenant_id = ? AND cluster_id = ?", (tenant_id, cluster_id))


def _backfill_history(snapshot, now, days=7):
    """Gera uma amostra por hora nos últimos dias, com o padrão diário de cada workload."""
    from analyzers.capacity import analyze_capacity
    from analyzers.workloads import collect_workloads
    from approval.store import save_metric_samples, save_workload_samples
    from collectors.snapshot import snapshot_to_data

    data = snapshot_to_data(snapshot)
    base_capacity = analyze_capacity(data["nodes"], data["pods"], data["node_metrics"], data["pod_metrics"])
    base_samples, _ = collect_workloads(data["pods"], data["container_metrics"])
    profiles = {f"{w[0]}/{w[2]}/{w[1]}/{w[1]}": w[9] for w in WORKLOADS}
    rng = random.Random(42)

    for step in range(days * 24, 0, -1):
        moment = now - timedelta(hours=step)
        hour_local = (moment.hour - 3) % 24
        samples = {}
        for key, value in base_samples.items():
            profile = profiles.get(key, "constante")
            f = _factor(profile, hour_local, rng) / max(_factor(profile, (now.hour - 3) % 24, random.Random(1)), 0.05)
            mem_f = 1.0 if value["mem_b"] > 1000 * MI else rng.uniform(0.85, 1.05)
            samples[key] = {"cpu_m": max(1, int(value["cpu_m"] * f)), "mem_b": int(value["mem_b"] * mem_f)}
        save_workload_samples(samples, timestamp=_ts(moment))

        capacity = copy.deepcopy(base_capacity)
        day_f = 0.75 + 0.35 * max(0.0, math.sin((hour_local - 6) / 24 * 2 * math.pi))
        for pool in capacity.values():
            m = pool.get("metrics", {})
            for k in ("cpu_usage_vs_alloc_pct", "mem_usage_vs_alloc_pct"):
                if m.get(k) is not None:
                    m[k] = round(m[k] * (day_f if k.startswith("cpu") else rng.uniform(0.95, 1.02)), 1)
        save_metric_samples(capacity, timestamp=_ts(moment))


def _seed_journal(tenant_id, cluster_id):
    from accounts.journal import create_entry, list_entries

    if list_entries(tenant_id, cluster_id, limit=1):
        return
    today = datetime.now(timezone.utc).date()
    create_entry(tenant_id, cluster_id, "Equipe Demo", "pendencia",
                 "Aumentar memória do redis (data/redis)",
                 "Uso real perto de 100% do request. Validar com o time de dados e aplicar na janela de quinta.",
                 assignee="Ana Ribeiro", due_date=(today - timedelta(days=1)).isoformat(),
                 link_type="recommendation", link_ref="data/StatefulSet/redis")
    create_entry(tenant_id, cluster_id, "Equipe Demo", "pendencia",
                 "Corrigir CrashLoop do reports/pdf-exporter",
                 "Imagem nova quebrou a variável de ambiente do bucket. Rollback ou correção do deploy.",
                 assignee="Bruno Costa", due_date=(today + timedelta(days=2)).isoformat())
    create_entry(tenant_id, cluster_id, "Equipe Demo", "nota", f"Nota de {today.strftime('%d/%m/%Y')}",
                 "Janela de manutenção confirmada para quinta às 22h. Black Friday congela mudanças a partir do dia 20.")


def seed_demo(email="demo@capacity-agent.local", password=None):
    from accounts.store import save_cost_settings, touch_agent_cluster
    from approval.store import save_cluster_snapshot
    from engine.evaluation import run_evaluation
    from tenant_context import current_cluster_id, current_cluster_mode, current_cluster_name, current_tenant_id

    created_password = password or secrets.token_urlsafe(9)
    tenant_id, created = _ensure_account(email, created_password)
    cluster = _ensure_cluster(tenant_id)
    now = datetime.now(timezone.utc)
    snapshot = build_snapshot(now)

    tokens = [
        (current_tenant_id, current_tenant_id.set(tenant_id)),
        (current_cluster_id, current_cluster_id.set(cluster["id"])),
        (current_cluster_name, current_cluster_name.set(cluster["name"])),
        (current_cluster_mode, current_cluster_mode.set("agent")),
    ]
    try:
        _clear_cluster_state(tenant_id, cluster["id"])
        _backfill_history(snapshot, now)
        save_cluster_snapshot(snapshot)
        touch_agent_cluster(cluster["id"], len(snapshot["nodes"]["items"]), context_name="demo")
        save_cost_settings(tenant_id, 150.0, 20.0)
        _seed_journal(tenant_id, cluster["id"])
        report = run_evaluation(source="demo", actor="Equipe Demo")
    finally:
        for var, value in reversed(tokens):
            var.reset(value)

    return {
        "email": email,
        "password": created_password if created else None,
        "created": created,
        "cluster": cluster["name"],
        "recommendations": len((report or {}).get("recommendations", [])) if isinstance(report, dict) else None,
    }
