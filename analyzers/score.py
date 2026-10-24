"""Resumo executivo da Visão Geral: nota de saúde, manchete, KPIs, riscos e economias.

Tudo é derivado do relatório já calculado (sem nova coleta), para que técnicos e
gestores leiam o mesmo número. Regras simples e explicáveis: cada desconto da
nota aparece em "factors".
"""

SEVERITY_ORDER = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
TYPE_LABELS = {
    "RIGHTSIZE_REQUESTS": "ajustar requests (sobra)",
    "INCREASE_REQUESTS": "aumentar requests",
    "MISSING_REQUESTS": "definir requests ausentes",
    "INCREASE_REPLICAS": "aumentar réplicas",
    "REDUCE_REPLICAS": "reduzir réplicas",
    "CREATE_HPA": "criar HPA",
    "HPA_AT_MAX": "HPA no limite",
    "HPA_WITHOUT_REQUESTS": "HPA sem requests",
    "UNDERUTILIZED_POOL": "pool de nodes subutilizado",
    "SCHEDULING_MEMORY": "pods sem memória para agendar",
    "SCHEDULING_CPU": "pods sem CPU para agendar",
    "SCHEDULING_COMBINED": "pods sem CPU e memória para agendar",
    "PVC_SCHEDULING": "pods presos por volume (PVC)",
    "UNKNOWN_SCHEDULING": "pods Pending",
}


def _fmt_brl(value):
    text = f"{abs(value):,.0f}".replace(",", ".")
    return f"R$ {text}"


def _cluster_efficiency(nodes):
    """CPU em uso / CPU reservada (requests), só nodes de trabalho com métrica."""
    used = req = 0.0
    for n in nodes:
        if n.get("control_plane") or n.get("cpu_usage_pct") is None:
            continue
        alloc = n.get("cpu_alloc_m") or 0
        used += alloc * n["cpu_usage_pct"] / 100
        req += alloc * (n.get("cpu_req_pct") or 0) / 100
    return round(used / req * 100) if req else None


def build_overview(report):
    from alerts.rules import build_alerts

    nodes = report.get("nodes_usage") or []
    summary = report.get("summary") or {}
    alerts = build_alerts(report)
    # Recomendação HIGH é "algo a ajustar", não incidente: na nota conta como atenção.
    # Riscos críticos são só os operacionais (node, pod quebrado, coletor parado).
    for a in alerts:
        if a["key"].startswith("rec:"):
            a["severity"] = "MEDIUM"
            rec_type = a["title"].replace("Recomendação crítica: ", "")
            a["title"] = "Ajuste recomendado: " + TYPE_LABELS.get(rec_type, rec_type)
    alerts.sort(key=lambda a: (SEVERITY_ORDER.get(a["severity"], 9), a["key"].startswith("rec:")))
    high = [a for a in alerts if a["severity"] == "HIGH"]
    medium = [a for a in alerts if a["severity"] == "MEDIUM" and not a["key"].startswith("rec:")]
    rec_alerts = [a for a in alerts if a["key"].startswith("rec:")]

    factors = []

    def penalty(points, reason):
        if points:
            factors.append({"points": -points, "reason": reason})

    penalty(min(60, 20 * len(high)), f"{len(high)} risco(s) crítico(s)")
    penalty(min(21, 7 * len(medium)), f"{len(medium)} ponto(s) de atenção")
    penalty(min(15, 3 * len(rec_alerts)), f"{len(rec_alerts)} ajuste(s) de alta prioridade pendente(s)")
    failed_checks = [c for c in (report.get("health") or {}).get("checks", []) if c.get("status") != "OK"]
    penalty(min(20, 10 * len(failed_checks)), "cobertura de métricas incompleta")

    efficiency = _cluster_efficiency(nodes)
    if efficiency is not None and efficiency < 30:
        penalty(10, f"baixa eficiência: só {efficiency}% da CPU reservada é usada")
    elif efficiency is not None and efficiency > 90:
        penalty(10, f"CPU reservada quase toda em uso ({efficiency}%)")

    workers = [n for n in nodes if not n.get("control_plane")]
    no_request_recs = [r for r in report.get("recommendations", []) if r.get("type") == "MISSING_REQUESTS"]
    penalty(min(10, 2 * len(no_request_recs)), "workloads sem requests definidos")

    score = max(0, 100 + sum(f["points"] for f in factors))
    if high:  # com risco crítico aberto o cluster nunca aparece como "Saudável"
        score = min(score, 79)
    status = "Saudável" if score >= 85 else "Atenção" if score >= 60 else "Crítico"

    savings_items = sorted(
        (r for r in report.get("recommendations", []) if (r.get("estimated_monthly") or 0) > 0),
        key=lambda r: -r["estimated_monthly"],
    )
    savings_total = round(sum(r["estimated_monthly"] for r in savings_items), 2)
    costs_on = bool((summary.get("cost_settings") or {}).get("cpu_month")
                    or (summary.get("cost_settings") or {}).get("gb_month"))

    ready = sum(1 for n in nodes if n.get("ready"))
    pods = summary.get("pods") or 0
    unhealthy = len(report.get("unhealthy_pods") or []) + (summary.get("pending_pods") or 0)
    pods_ok_pct = round((pods - unhealthy) / pods * 100, 1) if pods else None

    if high:
        headline = f"{len(high)} risco(s) crítico(s) exige(m) ação agora"
        explanation = high[0]["title"] + ". " + high[0]["detail"]
    elif medium or rec_alerts:
        first = (medium or rec_alerts)[0]
        headline = "Cluster operando, com pontos de atenção"
        explanation = first["title"] + ". " + first["detail"]
    elif savings_total > 0 and costs_on:
        headline = f"Cluster saudável, com {_fmt_brl(savings_total)}/mês de economia possível"
        explanation = "Nenhum risco ativo. As maiores economias estão listadas abaixo, prontas para aprovação."
    else:
        headline = "Cluster saudável"
        explanation = "Nenhum risco ativo encontrado na última avaliação."
    if efficiency is not None:
        explanation += f" Eficiência de CPU: {efficiency}% do reservado está em uso."

    return {
        "score": score,
        "status": status,
        "headline": headline,
        "explanation": explanation,
        "factors": factors,
        "kpis": {
            "risks": len(alerts),
            "risks_high": len(high),
            "savings_monthly": savings_total if costs_on else None,
            "savings_count": len(savings_items),
            "cpu_efficiency_pct": efficiency,
            "nodes_ready": ready,
            "nodes_total": len(nodes),
            "workers": len(workers),
            "pods_ok_pct": pods_ok_pct,
        },
        "top_risks": alerts[:3],
        "top_savings": [
            {"id": r.get("id"), "type": r.get("type"), "target": r.get("pool"),
             "action": r.get("action"), "monthly": r["estimated_monthly"],
             "executable": bool((r.get("operation") or {}).get("executable"))}
            for r in savings_items[:3]
        ],
    }
