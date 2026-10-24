from config import (
    CPU_USAGE_HIGH_PCT,
    CPU_USAGE_LOW_PCT,
    EFFICIENCY_LOW_PCT,
    MEM_USAGE_HIGH_PCT,
    REQUEST_ALLOC_HIGH_PCT,
)

# Alinhado com barClass() do dashboard (vermelho >= 85%)
STABILITY_REQUEST_HIGH_PCT = 85


def _suggestion(
    pool_name,
    severity,
    category,
    title,
    problem,
    action,
    impact,
    metrics,
    bucket,
):

    return {
        "pool": pool_name,
        "severity": severity,
        "category": category,
        "title": title,
        "problem": problem,
        "action": action,
        "impact": impact,
        "metrics": {
            "cpu_req_pct": metrics.get("cpu_req_vs_alloc_pct"),
            "mem_req_pct": metrics.get("mem_req_vs_alloc_pct"),
            "cpu_usage_pct": metrics.get("cpu_usage_vs_alloc_pct"),
            "mem_usage_pct": metrics.get("mem_usage_vs_alloc_pct"),
            "cpu_efficiency_pct": metrics.get("cpu_usage_vs_req_pct"),
            "mem_efficiency_pct": metrics.get("mem_usage_vs_req_pct"),
        },
        "nodes": bucket.get("node_count", 0),
        "pods": bucket.get("pod_count", 0),
    }


def suggest_pool_stability(pool_name, bucket, metrics):

    if bucket["node_count"] == 0:
        return []

    suggestions = []

    cpu_req = metrics["cpu_req_vs_alloc_pct"]
    mem_req = metrics["mem_req_vs_alloc_pct"]
    cpu_use = metrics["cpu_usage_vs_alloc_pct"]
    mem_use = metrics["mem_usage_vs_alloc_pct"]
    cpu_eff = metrics["cpu_usage_vs_req_pct"]
    mem_eff = metrics["mem_usage_vs_req_pct"]
    nodes = bucket["node_count"]
    pods = bucket["pod_count"]

    if mem_use >= MEM_USAGE_HIGH_PCT:
        suggestions.append(_suggestion(
            pool_name,
            "HIGH",
            "memory_usage_pressure",
            "Pressão real de memória",
            (
                f"Memória em uso: {mem_use}% do allocatable. "
                f"O pool está consumindo memória física acima do limite seguro."
            ),
            (
                "Expandir o pool (adicionar nodes ou máquinas com mais RAM) "
                "ou migrar workloads para outro pool. "
                "Investigar pods com maior consumo de memória."
            ),
            "Risco de eviction, OOMKill e instabilidade de aplicações.",
            metrics,
            bucket,
        ))

    if cpu_use >= CPU_USAGE_HIGH_PCT:
        suggestions.append(_suggestion(
            pool_name,
            "HIGH",
            "cpu_usage_pressure",
            "Pressão real de CPU",
            (
                f"CPU em uso: {cpu_use}% do allocatable. "
                "O pool está operando próximo da capacidade física."
            ),
            (
                "Expandir o pool ou redistribuir workloads. "
                "Verificar HPA/VPA e picos de consumo."
            ),
            "Degradação de performance e latência elevada nos serviços.",
            metrics,
            bucket,
        ))

    if mem_req >= STABILITY_REQUEST_HIGH_PCT and mem_eff < EFFICIENCY_LOW_PCT:
        suggestions.append(_suggestion(
            pool_name,
            "HIGH",
            "memory_request_block",
            "Requests de memória bloqueando agendamento",
            (
                f"Requests reservam {mem_req}% da capacidade, "
                f"mas uso real é apenas {mem_eff}% dos requests. "
                "O scheduler considera o pool cheio."
            ),
            (
                "Revisar e reduzir memory requests dos deployments "
                "(VPA recommendations ou análise por pod). "
                "Só expandir o pool se o uso real também estiver alto."
            ),
            "Novos pods ficam Pending mesmo com memória ociosa no pool.",
            metrics,
            bucket,
        ))

    if cpu_req >= STABILITY_REQUEST_HIGH_PCT and cpu_eff < EFFICIENCY_LOW_PCT:
        suggestions.append(_suggestion(
            pool_name,
            "HIGH",
            "cpu_request_block",
            "Requests de CPU bloqueando agendamento",
            (
                f"Requests reservam {cpu_req}% da capacidade, "
                f"mas uso real é apenas {cpu_eff}% dos requests."
            ),
            (
                "Prioridade: revisar CPU requests dos deployments neste pool. "
                "Muitos workloads declaram CPU acima do consumo real. "
                "Use kubectl top pods para identificar os maiores requests."
            ),
            "Principal causa de pods Pending por falta de CPU no cluster.",
            metrics,
            bucket,
        ))

    if (
        cpu_req >= 75
        and mem_req >= 75
        and cpu_eff < 50
        and mem_eff < 50
        and nodes <= 3
    ):
        suggestions.append(_suggestion(
            pool_name,
            "MEDIUM",
            "combined_overprovision",
            "Pool superprovisionado (CPU + memória)",
            (
                f"Requests elevados (CPU {cpu_req}%, Mem {mem_req}%) "
                f"com baixa eficiência de uso."
            ),
            (
                "Executar right-sizing em lote neste pool antes de escalar. "
                "Considerar VPA em modo recommendation."
            ),
            "Capacidade ociosa que impede crescimento do cluster.",
            metrics,
            bucket,
        ))

    if nodes == 1 and pods >= 10 and (cpu_req >= 80 or mem_req >= 80):
        suggestions.append(_suggestion(
            pool_name,
            "MEDIUM",
            "single_node_risk",
            "Pool com node único sob pressão",
            (
                f"Pool com 1 node, {pods} pods e requests elevados "
                f"(CPU {cpu_req}%, Mem {mem_req}%)."
            ),
            (
                "Adicionar ao menos mais 1 node para resiliência "
                "ou redistribuir pods para outro pool."
            ),
            "Sem redundância — falha do node derruba todos os workloads.",
            metrics,
            bucket,
        ))

    if (
        cpu_use < CPU_USAGE_LOW_PCT
        and cpu_req < 50
        and nodes > 2
        and mem_use < CPU_USAGE_LOW_PCT
    ):
        suggestions.append(_suggestion(
            pool_name,
            "LOW",
            "cost_optimization",
            "Pool subutilizado",
            (
                f"CPU em uso: {cpu_use}%, Memória: {mem_use}%. "
                f"{nodes} nodes com baixa utilização."
            ),
            (
                "Avaliar redução de nodes ou consolidação de workloads "
                "para otimizar custos (após validação DevOps)."
            ),
            "Oportunidade de redução de custo sem impacto operacional.",
            metrics,
            bucket,
        ))

    return suggestions


def _cluster_level_actions(pool_suggestions, summary, scheduling):

    actions = []

    request_blocks = [
        s for s in pool_suggestions
        if s["category"] in (
            "cpu_request_block",
            "memory_request_block",
            "combined_overprovision",
        )
    ]

    usage_pressure = [
        s for s in pool_suggestions
        if s["category"] in (
            "memory_usage_pressure",
            "cpu_usage_pressure",
        )
    ]

    pending = summary.get("pending_pods", 0)
    scheduling_issues = summary.get("scheduling_issues", 0)

    if request_blocks:
        pools = ", ".join(s["pool"] for s in request_blocks[:5])
        actions.append({
            "priority": 1,
            "severity": "HIGH",
            "title": "Right-sizing de requests (ação prioritária)",
            "action": (
                f"Revisar CPU/memory requests nos pools: {pools}. "
                "Requests inflados bloqueiam agendamento mesmo com recursos ociosos. "
                "Esta é frequentemente a forma mais rápida de restaurar estabilidade "
                "sem aumentar custos."
            ),
        })

    if usage_pressure:
        pools = ", ".join(s["pool"] for s in usage_pressure[:5])
        actions.append({
            "priority": 2,
            "severity": "HIGH",
            "title": "Expandir pools com pressão real",
            "action": (
                f"Pools com consumo físico elevado: {pools}. "
                "Aumentar nodes ou migrar workloads antes que ocorram evictions."
            ),
        })

    if pending > 0:
        actions.append({
            "priority": 3 if request_blocks else 1,
            "severity": "HIGH" if pending > 20 else "MEDIUM",
            "title": "Resolver pods Pending",
            "action": (
                f"{pending} pods não conseguem iniciar. "
                "Correlacionar com aba Scheduling — priorizar ConfigMaps ausentes, "
                "image pull e falta de capacidade."
            ),
        })

    if scheduling_issues > 50:
        causes = scheduling.get("causes", {})
        top = sorted(causes.items(), key=lambda x: x[1], reverse=True)[:3]
        cause_str = ", ".join(f"{c} ({n})" for c, n in top)
        actions.append({
            "priority": 4,
            "severity": "MEDIUM",
            "title": "Corrigir problemas de scheduling",
            "action": (
                f"{scheduling_issues} problemas detectados. "
                f"Principais causas: {cause_str}."
            ),
        })

    if not actions and not pool_suggestions:
        actions.append({
            "priority": 1,
            "severity": "LOW",
            "title": "Cluster estável",
            "action": (
                "Nenhum gargalo crítico identificado. "
                "Manter monitoramento periódico."
            ),
        })

    actions.sort(key=lambda a: a["priority"])
    return actions


def analyze_stability(capacity, scheduling_summary, cluster_summary):

    pool_suggestions = []

    for pool_name, pool_data in capacity.items():

        bucket = pool_data.get("capacity", {})

        if bucket.get("node_count", 0) == 0:
            continue

        metrics = pool_data.get("metrics", {})

        pool_suggestions.extend(
            suggest_pool_stability(pool_name, bucket, metrics)
        )

    severity_order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
    pool_suggestions.sort(
        key=lambda s: (
            severity_order.get(s["severity"], 9),
            -(s["metrics"].get("cpu_req_pct") or 0),
        )
    )

    high_count = sum(1 for s in pool_suggestions if s["severity"] == "HIGH")
    pending = cluster_summary.get("pending_pods", 0)

    if high_count >= 3 or pending > 50:
        status = "critical"
        status_label = "Instabilidade — ação imediata recomendada"
    elif high_count >= 1 or pending > 10:
        status = "attention"
        status_label = "Atenção — gargalos identificados"
    else:
        status = "stable"
        status_label = "Estável — monitoramento contínuo"

    cluster_actions = _cluster_level_actions(
        pool_suggestions,
        cluster_summary,
        scheduling_summary,
    )

    return {
        "status": status,
        "status_label": status_label,
        "pool_suggestions": pool_suggestions,
        "cluster_actions": cluster_actions,
        "high_priority_pools": [
            s["pool"] for s in pool_suggestions if s["severity"] == "HIGH"
        ],
        "summary": _build_summary(pool_suggestions, cluster_actions, status),
    }


def _build_summary(pool_suggestions, cluster_actions, status):

    if status == "stable":
        return "Cluster opera dentro dos parâmetros. Nenhuma ação urgente."

    high = [s for s in pool_suggestions if s["severity"] == "HIGH"]

    request_blocks = [
        s for s in high
        if "request_block" in s["category"] or s["category"] == "combined_overprovision"
    ]

    if request_blocks:
        pools = ", ".join(s["pool"] for s in request_blocks[:4])
        return (
            f"Gargalo principal: requests superprovisionados nos pools "
            f"{pools}. O cluster reserva capacidade que não é utilizada, "
            "impedindo novos pods de serem agendados. "
            "Priorize right-sizing antes de escalar nodes."
        )

    if high:
        pools = ", ".join(s["pool"] for s in high[:4])
        return (
            f"Pressão de recursos detectada nos pools {pools}. "
            "Avaliar expansão ou redistribuição de workloads."
        )

    return "Pontos de atenção identificados — revisar sugestões por pool."
