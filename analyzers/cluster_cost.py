"""Custo do cluster por node, com rateio para os workloads (estilo OpenCost).

1. Cada node recebe um preço:
   - "tabela": preço cadastrado pelo cliente para o tipo de máquina (label
     node.kubernetes.io/instance-type), o node pool ou o nome do node;
   - "aproximado": sem preço na tabela, usa vCPU × R$/vCPU + GB × R$/GB;
   - sem preço: fica fora do total (e aparece na cobertura).
2. O preço do node é dividido em parte CPU e parte memória (proporção
   R$/vCPU ÷ R$/GB, ou 7,5 : 1 quando não há referência — a mesma ordem de
   grandeza dos preços públicos das clouds).
3. Cada pod paga a fração do allocatable que reserva (requests). O que não é
   reservado por ninguém é "capacidade ociosa": dinheiro pago sem uso.
4. Custos fixos (Kubernetes gerenciado, load balancers, etc.) somam no total.

Tudo é somente leitura e calculado a partir da API do Kubernetes.
"""
from collections import defaultdict

from analyzers.providers import is_control_plane, node_pool
from collectors.metrics import parse_cpu, parse_memory

GIB = 1024 ** 3
HOURS_MONTH = 730
DEFAULT_CPU_GB_RATIO = 7.5
TOP_NAMESPACES = 12


def _machine(labels):
    return labels.get("node.kubernetes.io/instance-type") or labels.get("beta.kubernetes.io/instance-type") or ""


def build_cost_inputs(nodes, pods):
    """Resumo compacto de nodes e requests por node/namespace (sem dados sensíveis)."""
    out_nodes = []
    for node in nodes.get("items", []):
        meta, status = node.get("metadata", {}), node.get("status", {})
        labels = meta.get("labels", {}) or {}
        role_labels = sorted(l.split("/", 1)[1] for l in labels if l.startswith("node-role.kubernetes.io/"))
        role = labels.get("magnum.openstack.org/role") or (role_labels[0] if role_labels else "worker")
        alloc, cap = status.get("allocatable", {}) or {}, status.get("capacity", {}) or {}
        out_nodes.append({
            "name": meta.get("name", "-"),
            "pool": node_pool(labels, fallback=role),
            "machine": _machine(labels),
            "control_plane": is_control_plane(labels),
            "cpu_m": parse_cpu(alloc.get("cpu") or cap.get("cpu")),
            "mem_b": parse_memory(alloc.get("memory") or cap.get("memory")),
            "cpu_cap_m": parse_cpu(cap.get("cpu") or alloc.get("cpu")),
            "mem_cap_b": parse_memory(cap.get("memory") or alloc.get("memory")),
        })
    usage = defaultdict(lambda: defaultdict(lambda: [0, 0]))
    for pod in pods.get("items", []):
        spec, status = pod.get("spec", {}) or {}, pod.get("status", {}) or {}
        node_name = spec.get("nodeName")
        if not node_name or status.get("phase") in ("Succeeded", "Failed"):
            continue
        ns = (pod.get("metadata") or {}).get("namespace", "default")
        for container in spec.get("containers", []) or []:
            req = (container.get("resources") or {}).get("requests") or {}
            usage[node_name][ns][0] += parse_cpu(req.get("cpu"))
            usage[node_name][ns][1] += parse_memory(req.get("memory"))
    return {"nodes": out_nodes, "usage": {n: dict(v) for n, v in usage.items()}}


def _monthly(entry):
    price = float(entry.get("price") or 0)
    return price * HOURS_MONTH if entry.get("unit", "month") == "hour" else price


def price_node(node, settings):
    """Retorna (R$/mês, fonte) para um node."""
    keys = {k.lower() for k in (node.get("machine"), node.get("pool"), node.get("name")) if k}
    table = settings.get("machine_prices") or []
    for entry in table:  # match exato (máquina, pool ou nome do node)
        if str(entry.get("match", "")).strip().lower() in keys and float(entry.get("price") or 0) > 0:
            return round(_monthly(entry), 2), "tabela"
    for entry in table:  # "*" = preço padrão para qualquer node
        if str(entry.get("match", "")).strip() == "*" and float(entry.get("price") or 0) > 0:
            return round(_monthly(entry), 2), "tabela"
    cpu_month, gb_month = float(settings.get("cpu_month") or 0), float(settings.get("gb_month") or 0)
    if cpu_month or gb_month:
        value = node["cpu_cap_m"] / 1000 * cpu_month + node["mem_cap_b"] / GIB * gb_month
        return round(value, 2), "aproximado"
    return None, None


def _fixed(settings):
    items = []
    for f in settings.get("fixed_costs") or []:
        monthly, qty = float(f.get("monthly") or 0), float(f.get("qty") or 1)
        if monthly > 0 and qty > 0:
            items.append({"name": f.get("name") or "Custo fixo", "monthly": round(monthly * qty, 2),
                          "qty": qty, "unit_monthly": monthly})
    return items


def compute_cluster_cost(inputs, settings):
    settings = settings or {}
    nodes = (inputs or {}).get("nodes") or []
    usage = (inputs or {}).get("usage") or {}
    cpu_month, gb_month = float(settings.get("cpu_month") or 0), float(settings.get("gb_month") or 0)
    ratio = cpu_month / gb_month if cpu_month and gb_month else DEFAULT_CPU_GB_RATIO

    coverage = {"tabela": 0, "aproximado": 0, "sem_preco": 0}
    unpriced = set()
    per_node, by_ns = [], defaultdict(lambda: {"monthly": 0.0, "cpu_m": 0, "mem_b": 0})
    pools = defaultdict(lambda: {"nodes": 0, "monthly": 0.0, "idle_monthly": 0.0, "sources": set()})
    cpu_paid = mem_paid = vcpu_total = gb_total = 0.0

    for node in nodes:
        monthly, source = price_node(node, settings)
        if monthly is None:
            coverage["sem_preco"] += 1
            unpriced.add(node.get("machine") or node.get("pool"))
            continue
        coverage[source] += 1
        vcpu, gb = node["cpu_cap_m"] / 1000, node["mem_cap_b"] / GIB
        weight_cpu, weight_mem = vcpu * ratio, gb
        cpu_part = monthly * weight_cpu / (weight_cpu + weight_mem) if (weight_cpu + weight_mem) else monthly
        mem_part = monthly - cpu_part
        cpu_paid, mem_paid, vcpu_total, gb_total = cpu_paid + cpu_part, mem_paid + mem_part, vcpu_total + vcpu, gb_total + gb

        allocated = 0.0
        for ns, (req_cpu, req_mem) in (usage.get(node["name"]) or {}).items():
            share = (cpu_part * min(req_cpu / node["cpu_m"], 1) if node["cpu_m"] else 0) + \
                    (mem_part * min(req_mem / node["mem_b"], 1) if node["mem_b"] else 0)
            allocated += share
            by_ns[ns]["monthly"] += share
            by_ns[ns]["cpu_m"] += req_cpu
            by_ns[ns]["mem_b"] += req_mem
        allocated = min(allocated, monthly)
        idle = monthly - allocated
        pool = pools[node["pool"]]
        pool["nodes"] += 1
        pool["monthly"] += monthly
        pool["idle_monthly"] += idle
        pool["sources"].add(source)
        pool["machine"] = node.get("machine") or pool.get("machine") or ""
        pool["control_plane"] = node.get("control_plane", False)
        per_node.append({"name": node["name"], "pool": node["pool"], "machine": node.get("machine") or "",
                         "monthly": round(monthly, 2), "allocated": round(allocated, 2),
                         "idle": round(idle, 2), "source": source})

    nodes_monthly = sum(n["monthly"] for n in per_node)
    allocated_monthly = sum(n["allocated"] for n in per_node)
    idle_monthly = nodes_monthly - allocated_monthly
    fixed = _fixed(settings)
    fixed_monthly = sum(f["monthly"] for f in fixed)

    ns_rows = sorted(({"namespace": ns, "monthly": round(v["monthly"], 2), "cpu_m": v["cpu_m"],
                       "mem_b": v["mem_b"]} for ns, v in by_ns.items()), key=lambda r: -r["monthly"])
    if len(ns_rows) > TOP_NAMESPACES:
        rest = ns_rows[TOP_NAMESPACES:]
        ns_rows = ns_rows[:TOP_NAMESPACES] + [{"namespace": f"outros ({len(rest)})",
                                              "monthly": round(sum(r["monthly"] for r in rest), 2),
                                              "cpu_m": sum(r["cpu_m"] for r in rest),
                                              "mem_b": sum(r["mem_b"] for r in rest)}]

    pool_rows = {}
    for name, p in pools.items():
        pool_rows[name] = {
            "nodes": p["nodes"], "machine": p.get("machine", ""), "control_plane": p.get("control_plane", False),
            "monthly": round(p["monthly"], 2), "per_node": round(p["monthly"] / p["nodes"], 2) if p["nodes"] else 0,
            "idle_monthly": round(p["idle_monthly"], 2),
            "source": "tabela" if p["sources"] == {"tabela"} else "aproximado" if "tabela" not in p["sources"] else "misto",
        }

    priced = coverage["tabela"] + coverage["aproximado"]
    return {
        "configured": priced > 0 or fixed_monthly > 0,
        "accuracy": ("tabela" if priced and coverage["tabela"] == len(nodes)
                     else "aproximado" if priced else "sem_preco"),
        "total_monthly": round(nodes_monthly + fixed_monthly, 2),
        "nodes_monthly": round(nodes_monthly, 2),
        "allocated_monthly": round(allocated_monthly, 2),
        "idle_monthly": round(idle_monthly, 2),
        "idle_pct": round(idle_monthly / nodes_monthly * 100, 1) if nodes_monthly else None,
        "fixed_monthly": round(fixed_monthly, 2),
        "fixed": fixed,
        "coverage": coverage,
        "unpriced_types": sorted(t for t in unpriced if t),
        "machine_types": sorted({n.get("machine") or n.get("pool") for n in nodes if n.get("machine") or n.get("pool")}),
        "by_namespace": ns_rows,
        "by_pool": pool_rows,
        "nodes": per_node[:60],
        # Preço efetivo (derivado dos nodes) para estimar rightsizing de requests.
        "effective_cpu_month": round(cpu_paid / vcpu_total, 2) if vcpu_total else None,
        "effective_gb_month": round(mem_paid / gb_total, 2) if gb_total else None,
    }


# ── Histórico: horas de node de verdade (acompanha o autoscaling) ──────────

MAX_SAMPLE_GAP_H = 2.0      # uma amostra "vale" no máximo 2 h (lacunas não viram custo)
MIN_HISTORY_HOURS = 24      # abaixo disso o histórico ainda não é confiável
SPEND_WINDOW_DAYS = 7


def _parse_ts(value):
    from datetime import datetime, timezone

    ts = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)


def history_cost(cost, samples, now=None):
    """Custo pela média de nodes no histórico e gasto real dos últimos 7 dias.

    samples: linhas de metric_samples (timestamp, pool, node_count), uma por pool a cada
    avaliação/amostragem. Cada amostra pesa o tempo até a próxima (máx. 2 h).
    """
    from datetime import datetime, timedelta, timezone

    if not cost or not cost.get("by_pool") or not samples:
        return None
    now = now or datetime.now(timezone.utc)
    window_start = now - timedelta(days=SPEND_WINDOW_DAYS)
    by_pool = defaultdict(list)
    for s in samples:
        if s.get("pool") in cost["by_pool"] and s.get("node_count") is not None:
            by_pool[s["pool"]].append((_parse_ts(s["timestamp"]), float(s["node_count"])))

    pools, hours_seen = {}, 0.0
    nodes_monthly = spend_window = window_hours = 0.0
    for pool, rows in by_pool.items():
        rows.sort()
        weighted = hours = w_spend = w_hours = 0.0
        for i, (ts, count) in enumerate(rows):
            nxt = rows[i + 1][0] if i + 1 < len(rows) else now
            w = max(0.0, min((nxt - ts).total_seconds() / 3600, MAX_SAMPLE_GAP_H))
            weighted, hours = weighted + count * w, hours + w
            if ts >= window_start:
                w_spend, w_hours = w_spend + count * w, w_hours + w
        if not hours:
            continue
        per_node = cost["by_pool"][pool]["per_node"]
        avg = weighted / hours
        counts = [c for _, c in rows]
        pools[pool] = {"avg_nodes": round(avg, 2), "min_nodes": int(min(counts)), "max_nodes": int(max(counts)),
                       "now_nodes": cost["by_pool"][pool]["nodes"], "monthly": round(avg * per_node, 2)}
        nodes_monthly += avg * per_node
        spend_window += w_spend * per_node / HOURS_MONTH
        hours_seen, window_hours = max(hours_seen, hours), max(window_hours, w_hours)

    if hours_seen < MIN_HISTORY_HOURS:
        return {"available": False, "hours": round(hours_seen, 1), "min_hours": MIN_HISTORY_HOURS}

    fixed = cost.get("fixed_monthly") or 0
    monthly = nodes_monthly + fixed
    now_total = cost.get("total_monthly") or 0
    autoscaling = any(p["min_nodes"] != p["max_nodes"] for p in pools.values())
    return {
        "available": True,
        "hours": round(hours_seen, 1),
        "days": round(hours_seen / 24, 1),
        "monthly": round(monthly, 2),
        "nodes_monthly": round(nodes_monthly, 2),
        "diff_pct": round((monthly - now_total) / now_total * 100, 1) if now_total else None,
        "autoscaling": autoscaling,
        "spend_window": round(spend_window + fixed * window_hours / HOURS_MONTH, 2),
        "spend_window_days": round(window_hours / 24, 1),
        "pools": pools,
    }
