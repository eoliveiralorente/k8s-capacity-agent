from datetime import datetime


CAUSE_LABELS = {
    "SCHEDULING_COMBINED": "Múltiplas restrições impedindo execução de workloads",
    "MISSING_CONFIGMAP": "Configurações ausentes no ambiente",
    "MISSING_SECRET": "Credenciais ou secrets ausentes",
    "UNKNOWN": "Problemas não classificados — requer investigação",
    "IMAGE_PULL": "Falha ao obter imagens de container",
    "REGISTRY_AUTH": "Problemas de autenticação no registry de imagens",
    "REGISTRY_NOT_FOUND": "Imagem ou repositório não encontrado",
    "INSUFFICIENT_CPU": "Capacidade de CPU insuficiente",
    "INSUFFICIENT_MEMORY": "Capacidade de memória insuficiente",
    "VOLUME_OR_PVC": "Problemas de armazenamento (volumes/PVC)",
    "AUTOSCALER": "Autoscaler não expandiu a capacidade",
    "UNTOLERATED_TAINT": "Incompatibilidade entre nodes e workloads",
    "NODE_AFFINITY": "Restrições de afinidade de nodes",
    "CONTAINER_RUNTIME": "Falha na execução de containers",
    "EVICTION": "Pods removidos por pressão de recursos",
    "POD_DISRUPTION": "Instabilidade ou reinício de aplicações",
}

REC_TYPE_LABELS = {
    "CPU_PRESSURE": "Pressão de CPU no cluster",
    "MEMORY_PRESSURE": "Pressão de memória no cluster",
    "UNDERUTILIZED_POOL": "Recursos subutilizados — oportunidade de otimização",
    "CPU_OVERPROVISIONED": "CPU reservada acima do consumo real",
    "SCHEDULING_CPU": "Workloads aguardando CPU disponível",
    "SCHEDULING_MEMORY": "Workloads aguardando memória disponível",
    "MISSING_CONFIGMAP": "Aplicações com configuração incompleta",
    "MISSING_SECRET": "Aplicações com credenciais ausentes",
    "IMAGE_PULL": "Aplicações não iniciadas por falha de imagem",
    "CLUSTER_AUTOSCALER": "Capacidade não expandida automaticamente",
}


def _format_date(iso):

    if not iso:
        return "—"

    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return dt.strftime("%d/%m/%Y às %H:%M")
    except ValueError:
        return iso[:16]


def _overall_status(report):

    summary = report.get("summary", {})
    health = report.get("health", {})
    recommendations = report.get("recommendations", [])

    high_recs = [r for r in recommendations if r.get("severity") == "HIGH"]
    pending_pods = summary.get("pending_pods", 0)
    scheduling_issues = summary.get("scheduling_issues", 0)

    if (
        pending_pods > 50
        or len(high_recs) >= 5
        or not health.get("decision_allowed", True)
    ):
        return {
            "level": "critical",
            "label": "Crítico",
            "summary": (
                "O ambiente requer atenção imediata da equipe técnica. "
                "Existem impactos significativos na operação que podem "
                "afetar disponibilidade de serviços."
            ),
        }

    if pending_pods > 10 or scheduling_issues > 20 or high_recs:
        return {
            "level": "attention",
            "label": "Atenção",
            "summary": (
                "O ambiente apresenta pontos de atenção que devem ser "
                "acompanhados. Recomenda-se revisão com a equipe DevOps "
                "para priorização de ações corretivas."
            ),
        }

    return {
        "level": "healthy",
        "label": "Estável",
        "summary": (
            "O ambiente opera dentro dos parâmetros esperados. "
            "Não há impactos críticos identificados nesta avaliação."
        ),
    }


def _capacity_highlights(capacity):

    highlights = []

    for pool_name, pool_data in sorted(capacity.items()):

        metrics = pool_data.get("metrics", {})
        bucket = pool_data.get("capacity", {})

        cpu_req = metrics.get("cpu_req_vs_alloc_pct", 0)
        mem_req = metrics.get("mem_req_vs_alloc_pct", 0)
        cpu_usage = metrics.get("cpu_usage_vs_alloc_pct", 0)
        mem_usage = metrics.get("mem_usage_vs_alloc_pct", 0)

        if cpu_req >= 85 or mem_req >= 85:
            highlights.append({
                "pool": pool_name,
                "type": "pressure",
                "label": "Capacidade reservada elevada",
                "detail": (
                    f"Pool com {bucket.get('node_count', 0)} nodes e "
                    f"{bucket.get('pod_count', 0)} pods. "
                    f"CPU reservada: {cpu_req}%, Memória reservada: {mem_req}%."
                ),
                "severity": "HIGH",
            })
        elif cpu_usage >= 80 or mem_usage >= 85:
            highlights.append({
                "pool": pool_name,
                "type": "usage",
                "label": "Consumo elevado de recursos",
                "detail": (
                    f"CPU em uso: {cpu_usage}%, Memória em uso: {mem_usage}%."
                ),
                "severity": "HIGH",
            })
        elif (
            cpu_usage < 30
            and cpu_req < 50
            and bucket.get("node_count", 0) > 1
        ):
            highlights.append({
                "pool": pool_name,
                "type": "underutilized",
                "label": "Recursos subutilizados",
                "detail": (
                    f"CPU em uso: {cpu_usage}%. "
                    "Oportunidade de otimização de custos."
                ),
                "severity": "LOW",
            })

    severity_order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
    highlights.sort(key=lambda x: severity_order.get(x["severity"], 9))

    return highlights[:8]


def _scheduling_highlights(scheduling):

    causes = scheduling.get("causes", {})
    namespaces = scheduling.get("namespaces", {})

    cause_items = []

    for cause, count in sorted(
        causes.items(),
        key=lambda x: x[1],
        reverse=True,
    )[:6]:
        cause_items.append({
            "cause": cause,
            "label": CAUSE_LABELS.get(cause, cause.replace("_", " ").title()),
            "count": count,
        })

    ns_items = []

    for ns, counter in sorted(
        namespaces.items(),
        key=lambda item: sum(item[1].values()),
        reverse=True,
    )[:8]:
        ns_items.append({
            "namespace": ns,
            "total": sum(counter.values()),
            "top_cause": max(counter.items(), key=lambda x: x[1])[0],
        })

    return {
        "causes": cause_items,
        "namespaces": ns_items,
        "total_issues": sum(causes.values()),
    }


def _executive_recommendations(recommendations):

    items = []

    for rec in recommendations:
        items.append({
            "id": rec.get("id"),
            "type": rec.get("type"),
            "label": REC_TYPE_LABELS.get(
                rec.get("type"),
                rec.get("type", "").replace("_", " ").title(),
            ),
            "severity": rec.get("severity", "MEDIUM"),
            "action": rec.get("action", ""),
            "pool": rec.get("pool"),
            "affected_pods": rec.get("affected_pods", 0),
            "status": rec.get("status", "pending"),
            "executable": rec.get("operation", {}).get("executable", False),
        })

    severity_order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
    items.sort(key=lambda x: severity_order.get(x["severity"], 9))

    return items[:12]


def build_executive_report(report):

    status = _overall_status(report)
    summary = report.get("summary", {})
    health = report.get("health", {})
    scheduling = report.get("scheduling", {})
    capacity = report.get("capacity", {})
    recommendations = report.get("recommendations", [])

    pending = [r for r in recommendations if r.get("status") == "pending"]
    high_pending = [r for r in pending if r.get("severity") == "HIGH"]

    return {
        "meta": {
            "evaluation_id": report.get("evaluation_id"),
            "cluster": report.get("cluster"),
            "generated_at": _format_date(report.get("created_at")),
            "generated_at_iso": report.get("created_at"),
            "document_type": "Relatório Executivo de Capacity",
            "audience": "Gerentes e Supervisores",
        },
        "status": status,
        "kpis": {
            "nodes": summary.get("nodes", 0),
            "pods": summary.get("pods", 0),
            "node_pools": summary.get("node_pools", 0),
            "pending_pods": summary.get("pending_pods", 0),
            "scheduling_issues": summary.get("scheduling_issues", 0),
            "recommendations_total": len(recommendations),
            "recommendations_pending": len(pending),
            "recommendations_high": len(high_pending),
            "health_ok": health.get("decision_allowed", False),
            "node_coverage": health.get("node_coverage", 0),
            "pod_coverage": health.get("pod_coverage", 0),
        },
        "capacity_highlights": _capacity_highlights(capacity),
        "scheduling": _scheduling_highlights(scheduling),
        "recommendations": _executive_recommendations(recommendations),
        "action_plan": {
            "requires_devops_review": len(pending) > 0,
            "pending_approvals": len(pending),
            "high_priority_items": len(high_pending),
            "next_steps": _build_next_steps(
                status,
                pending,
                high_pending,
                summary,
            ),
        },
    }


def _build_next_steps(status, pending, high_pending, summary):

    steps = []

    if status["level"] == "critical":
        steps.append(
            "Convocar reunião com DevOps para avaliar impacto "
            "operacional imediato."
        )

    if summary.get("pending_pods", 0) > 0:
        steps.append(
            f"Acompanhar {summary['pending_pods']} pods que não "
            "conseguiram iniciar — podem afetar entregas e jobs."
        )

    if high_pending:
        steps.append(
            f"Priorizar análise de {len(high_pending)} recomendação(ões) "
            "de alta severidade aguardando aprovação DevOps."
        )

    if pending:
        steps.append(
            "Validar com DevOps o plano de ação antes de "
            "autorizar alterações no ambiente."
        )

    if not steps:
        steps.append(
            "Manter monitoramento periódico. "
            "Próxima avaliação conforme calendário operacional."
        )

    return steps


def write_executive_html(report, output_path):

    import json
    from pathlib import Path

    from engine.evaluation import summarize_report_for_api

    data = build_executive_report(summarize_report_for_api(report))
    static_dir = Path(__file__).parent.parent / "web" / "static"
    css_path = static_dir / "relatorio.css"
    js_path = static_dir / "relatorio.js"

    css = css_path.read_text(encoding="utf-8") if css_path.exists() else ""
    js_content = js_path.read_text(encoding="utf-8") if js_path.exists() else ""

    data_json = json.dumps(data, ensure_ascii=False)

    html = f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
  <meta charset="UTF-8">
  <title>Relatório Executivo — {data['meta']['cluster']}</title>
  <style>{css}</style>
</head>
<body>
  <div class="toolbar no-print">
    <div class="toolbar-right" style="margin-left:auto">
      <button class="btn btn-primary" onclick="window.print()">Exportar PDF / Imprimir</button>
    </div>
  </div>
  <article class="report" id="report"></article>
  <script>
    const REPORT_DATA = {data_json};
    {js_content}
    renderReport(REPORT_DATA);
  </script>
</body>
</html>"""

    Path(output_path).write_text(html, encoding="utf-8")

    return output_path
