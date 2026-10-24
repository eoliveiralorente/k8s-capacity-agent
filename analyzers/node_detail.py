"""Detalhe de um node: dados do node e o que está rodando nele."""
from analyzers.nodes import analyze_nodes
from analyzers.workloads import workload_owner
from collectors.metrics import parse_cpu, parse_memory

MI = 1024 ** 2
INTERESTING_LABELS = (
    "node.kubernetes.io/instance-type", "topology.kubernetes.io/zone", "topology.kubernetes.io/region",
    "kubernetes.io/os", "kubernetes.io/arch",
)


def build_node_detail(node_name, nodes, pods, node_metrics, pod_metrics):
    node = next((n for n in nodes.get("items", []) if n.get("metadata", {}).get("name") == node_name), None)
    if not node:
        return None
    meta, spec, status = node.get("metadata", {}), node.get("spec", {}), node.get("status", {})
    usage = next((u for u in analyze_nodes({"items": [node]}, pods, node_metrics)), {})
    info = status.get("nodeInfo", {})
    conditions = [
        {"type": c.get("type"), "status": c.get("status"), "reason": c.get("reason"), "message": c.get("message")}
        for c in status.get("conditions", [])
        if (c.get("type") == "Ready" and c.get("status") != "True") or (c.get("type") != "Ready" and c.get("status") == "True")
    ]

    rows = []
    for pod in pods.get("items", []):
        if pod.get("spec", {}).get("nodeName") != node_name:
            continue
        pmeta, pspec, pstatus = pod.get("metadata", {}), pod.get("spec", {}), pod.get("status", {})
        if pstatus.get("phase") in ("Succeeded", "Failed"):
            continue
        cpu_req = mem_req = 0
        missing = False
        for c in pspec.get("containers", []):
            req = (c.get("resources") or {}).get("requests") or {}
            cpu_req += parse_cpu(req.get("cpu"))
            mem_req += parse_memory(req.get("memory"))
            missing = missing or not req.get("cpu") or not req.get("memory")
        statuses = pstatus.get("containerStatuses", []) or []
        waiting = next((s.get("state", {}).get("waiting", {}).get("reason") for s in statuses
                        if s.get("state", {}).get("waiting")), None)
        owner = workload_owner(pod)
        key = f"{pmeta.get('namespace')}/{pmeta.get('name')}"
        used = pod_metrics.get(key) or {}
        rows.append({
            "namespace": pmeta.get("namespace"),
            "pod": pmeta.get("name"),
            "workload": f"{owner[0]}/{owner[1]}" if owner else (pmeta.get("ownerReferences") or [{}])[0].get("kind", "Pod"),
            "status": waiting or pstatus.get("phase"),
            "restarts": sum(s.get("restartCount", 0) for s in statuses),
            "qos": pstatus.get("qosClass"),
            "cpu_used_m": used.get("cpu_m"),
            "mem_used_mi": round(used["mem_b"] / MI) if used.get("mem_b") is not None else None,
            "cpu_req_m": cpu_req,
            "mem_req_mi": round(mem_req / MI),
            "missing_requests": missing,
        })
    rows.sort(key=lambda r: (-(r["mem_used_mi"] or 0), r["namespace"], r["pod"]))

    namespaces = {}
    for r in rows:
        ns = namespaces.setdefault(r["namespace"], {"namespace": r["namespace"], "pods": 0, "cpu_used_m": 0, "mem_used_mi": 0})
        ns["pods"] += 1
        ns["cpu_used_m"] += r["cpu_used_m"] or 0
        ns["mem_used_mi"] += r["mem_used_mi"] or 0

    return {
        "name": node_name,
        "pool": usage.get("pool"),
        "control_plane": usage.get("control_plane"),
        "ready": usage.get("ready"),
        "labels": {k: v for k, v in (meta.get("labels") or {}).items() if k in INTERESTING_LABELS},
        "kubelet": info.get("kubeletVersion"),
        "os_image": info.get("osImage"),
        "runtime": info.get("containerRuntimeVersion"),
        "taints": spec.get("taints", []),
        "unschedulable": bool(spec.get("unschedulable")),
        "conditions_alert": conditions,
        "usage": usage,
        "pods": rows,
        "namespaces": sorted(namespaces.values(), key=lambda n: -n["mem_used_mi"]),
        "pods_without_requests": sum(1 for r in rows if r["missing_requests"]),
    }
