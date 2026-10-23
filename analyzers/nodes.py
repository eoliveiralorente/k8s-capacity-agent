"""Consumo por node: uso real (kubectl top) e reservado (requests) vs allocatable."""
from analyzers.providers import is_control_plane, node_pool
from collectors.metrics import parse_cpu, parse_memory


def _pct(value, total):
    return round(value / total * 100, 1) if total else 0.0


def analyze_nodes(nodes, pods, node_metrics):
    info = {}
    for node in nodes.get("items", []):
        metadata, status = node.get("metadata", {}), node.get("status", {})
        labels = metadata.get("labels", {})
        name = metadata.get("name", "-")
        allocatable = status.get("allocatable", {})
        ready = any(c.get("type") == "Ready" and c.get("status") == "True"
                    for c in status.get("conditions", []))
        role_labels = sorted(l.split("/", 1)[1] for l in labels if l.startswith("node-role.kubernetes.io/"))
        info[name] = {
            "name": name,
            "pool": node_pool(labels, fallback=role_labels[0] if role_labels else "worker"),
            "control_plane": is_control_plane(labels),
            "ready": ready,
            "cpu_alloc_m": parse_cpu(allocatable.get("cpu", "0")),
            "mem_alloc_b": parse_memory(allocatable.get("memory", "0")),
            "pods_capacity": int(allocatable.get("pods", "0") or 0),
            "cpu_req_m": 0, "mem_req_b": 0, "pod_count": 0,
        }

    for pod in pods.get("items", []):
        node_name = pod.get("spec", {}).get("nodeName")
        if node_name not in info or pod.get("status", {}).get("phase") in ("Succeeded", "Failed"):
            continue
        bucket = info[node_name]
        bucket["pod_count"] += 1
        for container in pod.get("spec", {}).get("containers", []):
            requests = (container.get("resources", {}) or {}).get("requests", {}) or {}
            bucket["cpu_req_m"] += parse_cpu(requests.get("cpu"))
            bucket["mem_req_b"] += parse_memory(requests.get("memory"))

    result = []
    for name, n in sorted(info.items(), key=lambda item: (item[1]["pool"], item[0])):
        usage = node_metrics.get(name)
        cpu_used = parse_cpu(usage["cpu"]) if usage else None
        mem_used = parse_memory(usage["mem"]) if usage else None
        result.append({
            "name": name,
            "pool": n["pool"],
            "control_plane": n["control_plane"],
            "ready": n["ready"],
            "pod_count": n["pod_count"],
            "pods_capacity": n["pods_capacity"],
            "cpu_usage_pct": _pct(cpu_used, n["cpu_alloc_m"]) if usage else None,
            "mem_usage_pct": _pct(mem_used, n["mem_alloc_b"]) if usage else None,
            "cpu_req_pct": _pct(n["cpu_req_m"], n["cpu_alloc_m"]),
            "mem_req_pct": _pct(n["mem_req_b"], n["mem_alloc_b"]),
            "cpu_alloc_m": n["cpu_alloc_m"],
            "mem_alloc_b": n["mem_alloc_b"],
        })
    return result
