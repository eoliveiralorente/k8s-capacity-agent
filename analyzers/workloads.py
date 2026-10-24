"""Rightsizing de requests por container (agnóstico de cloud).

Chave de workload: "namespace/Kind/nome/container".
Proposta:
  CPU     = p95 do uso × margem (mín. 10m, múltiplos de 5m)
  Memória = pico do uso × margem (mín. 32Mi, múltiplos de 1Mi) — memória usa o
            pico porque falta de memória mata o container (OOMKilled).
"""
import math
import os
from datetime import datetime

from collectors.metrics import parse_cpu, parse_memory

MI = 1024 ** 2
CPU_MARGIN = 1.3
MEM_MARGIN = 1.3
MIN_CPU_M = 10
MIN_MEM_B = 32 * MI
REDUCE_FACTOR = 1.5          # só reduz se o request atual for 1,5× a proposta
MIN_CPU_SAVING_M = 50
MIN_MEM_SAVING_B = 64 * MI
PRESSURE_RATIO = 0.9         # uso ≥ 90% do request → aumentar

MIN_SAMPLES_MEDIUM = 12
MIN_SAMPLES_HIGH = 96
MIN_HOURS_HIGH = 72

SUPPORTED_KINDS = {"Deployment", "StatefulSet", "DaemonSet"}
PROTECTED_NAMESPACES = {
    ns.strip() for ns in os.getenv(
        "CAPACITY_AGENT_PROTECTED_NAMESPACES",
        "kube-system,kube-public,kube-node-lease,monitoring",
    ).split(",") if ns.strip()
}


def workload_owner(pod):
    """Retorna (kind, nome) do controlador do pod, ou None."""
    metadata = pod.get("metadata", {})
    owners = metadata.get("ownerReferences") or []
    if not owners:
        return None
    owner = owners[0]
    kind, name = owner.get("kind"), owner.get("name", "")
    if kind == "ReplicaSet":
        pod_hash = metadata.get("labels", {}).get("pod-template-hash")
        if pod_hash and name.endswith(f"-{pod_hash}"):
            return "Deployment", name[: -(len(pod_hash) + 1)]
        return None
    if kind in SUPPORTED_KINDS:
        return kind, name
    return None


def collect_workloads(pods, container_metrics):
    """Agrupa uso por workload/container e captura requests/limits atuais.

    Retorna (samples, specs):
      samples = {key: {"cpu_m", "mem_b"}}  — máximo entre as réplicas agora
      specs   = {key: {"namespace","kind","name","container","cpu_req_m","mem_req_b","cpu_lim_m","mem_lim_b"}}
    """
    samples, specs = {}, {}
    for pod in pods.get("items", []):
        if pod.get("status", {}).get("phase") != "Running":
            continue
        owner = workload_owner(pod)
        if not owner:
            continue
        kind, name = owner
        namespace = pod.get("metadata", {}).get("namespace", "default")
        pod_name = pod.get("metadata", {}).get("name", "")
        for container in pod.get("spec", {}).get("containers", []):
            cname = container.get("name", "")
            key = f"{namespace}/{kind}/{name}/{cname}"
            resources = container.get("resources", {})
            requests = resources.get("requests", {}) or {}
            limits = resources.get("limits", {}) or {}
            specs.setdefault(key, {
                "namespace": namespace, "kind": kind, "name": name, "container": cname,
                "cpu_req_m": parse_cpu(requests.get("cpu")),
                "mem_req_b": parse_memory(requests.get("memory")),
                "cpu_lim_m": parse_cpu(limits.get("cpu")),
                "mem_lim_b": parse_memory(limits.get("memory")),
                "replicas": 0,
            })
            specs[key]["replicas"] += 1
            usage = container_metrics.get((namespace, pod_name, cname))
            if usage:
                current = samples.setdefault(key, {"cpu_m": 0, "mem_b": 0})
                current["cpu_m"] = max(current["cpu_m"], usage["cpu_m"])
                current["mem_b"] = max(current["mem_b"], usage["mem_b"])
    return samples, specs


def _percentile(values, pct):
    values = sorted(values)
    if not values:
        return 0
    return values[max(0, min(len(values) - 1, round(pct / 100 * (len(values) - 1))))]


def _confidence(series):
    count = len(series)
    try:
        hours = (datetime.fromisoformat(series[-1][0]) - datetime.fromisoformat(series[0][0])).total_seconds() / 3600
    except (IndexError, ValueError):
        hours = 0
    if count >= MIN_SAMPLES_HIGH and hours >= MIN_HOURS_HIGH:
        return "alta", hours
    if count >= MIN_SAMPLES_MEDIUM:
        return "media", hours
    return "baixa", hours


def fmt_cpu(m):
    return f"{int(m)}m"


def fmt_mem(b):
    return f"{int(math.ceil(b / MI))}Mi"


def rightsizing_recommendations(specs, history):
    recs = []
    for key, spec in specs.items():
        series = history.get(key) or []
        if not series:
            continue
        confidence, hours = _confidence(series)
        cpu_p95 = _percentile([s[1] for s in series], 95)
        mem_max = max(s[2] for s in series)

        proposed_cpu = max(MIN_CPU_M, int(math.ceil(cpu_p95 * CPU_MARGIN / 5.0) * 5))
        proposed_mem = max(MIN_MEM_B, int(math.ceil(mem_max * MEM_MARGIN / MI) * MI))

        cur_cpu, cur_mem = spec["cpu_req_m"], spec["mem_req_b"]
        new_cpu, new_mem = cur_cpu, cur_mem
        reasons, direction = [], set()

        if cur_cpu == 0:
            new_cpu = proposed_cpu
            reasons.append("CPU sem request definido")
            direction.add("up")
        elif cpu_p95 >= cur_cpu * PRESSURE_RATIO:
            new_cpu = max(proposed_cpu, cur_cpu)
            reasons.append(f"CPU p95 {fmt_cpu(cpu_p95)} perto do request {fmt_cpu(cur_cpu)}")
            direction.add("up")
        elif cur_cpu >= proposed_cpu * REDUCE_FACTOR and cur_cpu - proposed_cpu >= MIN_CPU_SAVING_M:
            new_cpu = proposed_cpu
            reasons.append(f"CPU p95 {fmt_cpu(cpu_p95)} muito abaixo do request {fmt_cpu(cur_cpu)}")
            direction.add("down")

        if cur_mem == 0:
            new_mem = proposed_mem
            reasons.append("memória sem request definido")
            direction.add("up")
        elif mem_max >= cur_mem * PRESSURE_RATIO:
            new_mem = max(proposed_mem, cur_mem)
            reasons.append(f"memória pico {fmt_mem(mem_max)} perto do request {fmt_mem(cur_mem)}")
            direction.add("up")
        elif cur_mem >= proposed_mem * REDUCE_FACTOR and cur_mem - proposed_mem >= MIN_MEM_SAVING_B:
            new_mem = proposed_mem
            reasons.append(f"memória pico {fmt_mem(mem_max)} muito abaixo do request {fmt_mem(cur_mem)}")
            direction.add("down")

        if not reasons:
            continue

        blockers = []
        if spec["namespace"] in PROTECTED_NAMESPACES:
            blockers.append(f"namespace protegido ({spec['namespace']})")
        if confidence == "baixa":
            blockers.append("histórico insuficiente (confiança baixa)")
        if spec["cpu_lim_m"] and new_cpu > spec["cpu_lim_m"]:
            blockers.append("novo request de CPU acima do limit")
        if spec["mem_lim_b"] and new_mem > spec["mem_lim_b"]:
            blockers.append("novo request de memória acima do limit")

        period = f"{hours / 24:.1f} dias" if hours >= 24 else f"{hours:.0f} h"
        target = f"{spec['kind'].lower()}/{spec['name']}"
        action = (
            f"Ajustar requests de {target} (container {spec['container']}, ns {spec['namespace']}): "
            f"CPU {fmt_cpu(cur_cpu) if cur_cpu else '—'} → {fmt_cpu(new_cpu)}, "
            f"memória {fmt_mem(cur_mem) if cur_mem else '—'} → {fmt_mem(new_mem)}. "
            f"Motivo: {'; '.join(reasons)}. Base: {len(series)} amostras em {period}, confiança {confidence}. "
            "Aplicar reinicia os pods do workload (rolling update)."
        )

        severity = "MEDIUM" if "up" in direction else "LOW"
        if "up" in direction and any("memória" in r and "perto" in r for r in reasons):
            severity = "HIGH"

        params = {
            "namespace": spec["namespace"], "kind": spec["kind"], "name": spec["name"],
            "container": spec["container"],
            "current": {"cpu": fmt_cpu(cur_cpu) if cur_cpu else None,
                        "memory": fmt_mem(cur_mem) if cur_mem else None},
            "target": {"cpu": fmt_cpu(new_cpu), "memory": fmt_mem(new_mem)},
            "replicas": spec.get("replicas", 1),
            "delta": {"cpu_m": (cur_cpu - new_cpu) * spec.get("replicas", 1),
                      "mem_b": (cur_mem - new_mem) * spec.get("replicas", 1)},
        }
        if blockers:
            operation = {"kind": "manual_review", "executable": False,
                         "params": {**params, "reason": "; ".join(blockers)},
                         "dry_run_command": None, "execute_command": None}
        else:
            operation = {"kind": "k8s_set_resources", "executable": True, "params": params}

        recs.append({
            "type": "RIGHTSIZE_REQUESTS" if direction == {"down"} else "INCREASE_REQUESTS",
            "severity": severity,
            "pool": key,
            "source": "workload",
            "action": action,
            "message": action,
            "confidence": confidence,
            "operation": operation,
        })
    return recs
