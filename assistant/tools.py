"""Ferramentas SOMENTE LEITURA que o assistente pode consultar.

Nenhuma ferramenta altera o cluster. Os resultados passam por mascaramento
antes de ir ao modelo.
"""
import json

from tenant_context import current_cluster_mode

MAX_RESULT_CHARS = 12000


def _pods_and_events():
    if current_cluster_mode.get() == "agent":
        from approval.store import load_cluster_snapshot

        snapshot = load_cluster_snapshot() or {}
        return snapshot.get("pods") or {"items": []}, snapshot.get("events") or {"items": []}
    from collectors.kubernetes import get_cluster_events, get_pods

    return get_pods(), get_cluster_events()


def _latest_report():
    from approval.store import load_latest_report
    from engine.evaluation import summarize_report_for_api

    report = load_latest_report()
    return summarize_report_for_api(report) if report else None


def tool_cluster_summary(_args, _ctx):
    report = _latest_report()
    if not report:
        return {"erro": "Nenhuma avaliação ainda. Peça ao usuário para clicar em Nova Avaliação."}
    return {
        "avaliado_em": report.get("created_at"),
        "resumo": report.get("summary"),
        "saude": report.get("health"),
        "decisao": report.get("decision"),
        "consumo_por_node": report.get("nodes_usage"),
        "causas_scheduling": report.get("scheduling", {}).get("causes"),
    }


def tool_problem_pods(args, _ctx):
    from collectors.kubernetes import parse_cluster_pods

    pods, _ = _pods_and_events()
    namespace = (args or {}).get("namespace")
    rows = []
    for pod in parse_cluster_pods(pods):
        if namespace and pod["namespace"] != namespace:
            continue
        if pod["status"] not in ("Running", "Completed") or pod["restarts"] > 0 or \
                pod["ready"].split("/")[0] != pod["ready"].split("/")[-1] and pod["status"] != "Completed":
            rows.append(pod)
    rows.sort(key=lambda p: (-p["restarts"], p["namespace"], p["name"]))
    return {"total": len(rows), "pods": rows[:50]}


def tool_pod_details(args, _ctx):
    namespace, name = (args or {}).get("namespace"), (args or {}).get("pod")
    if not namespace or not name:
        return {"erro": "Informe namespace e pod"}
    pods, events = _pods_and_events()
    pod = next((p for p in pods.get("items", [])
                if p.get("metadata", {}).get("namespace") == namespace
                and p.get("metadata", {}).get("name") == name), None)
    if not pod:
        return {"erro": f"Pod {namespace}/{name} não encontrado"}
    spec, status = pod.get("spec", {}), pod.get("status", {})
    containers = []
    for c in spec.get("containers", []):
        st = next((s for s in status.get("containerStatuses", []) if s.get("name") == c.get("name")), {})
        containers.append({
            "nome": c.get("name"), "imagem": c.get("image"),
            "resources": c.get("resources"),
            "pronto": st.get("ready"), "reinicios": st.get("restartCount"),
            "estado": st.get("state"), "ultimo_estado": st.get("lastState"),
        })
    pod_events = [
        {"tipo": e.get("type"), "motivo": e.get("reason"), "mensagem": e.get("message") or e.get("note"),
         "vezes": e.get("count"), "ultimo": e.get("lastTimestamp") or e.get("eventTime")}
        for e in events.get("items", [])
        if (e.get("involvedObject") or e.get("regarding") or {}).get("name") == name
        and (e.get("involvedObject") or e.get("regarding") or {}).get("namespace", namespace) == namespace
    ][-20:]
    return {
        "pod": f"{namespace}/{name}", "node": spec.get("nodeName"), "fase": status.get("phase"),
        "condicoes": status.get("conditions"), "qos": status.get("qosClass"),
        "containers": containers, "eventos": pod_events,
    }


def tool_pod_logs(args, ctx):
    if ctx.get("role") not in ("operador", "admin"):
        return {"erro": "Logs disponíveis apenas para operador ou admin"}
    if current_cluster_mode.get() == "agent":
        return {"erro": "Logs indisponíveis em cluster conectado via agente (somente leitura)"}
    from collectors.kubernetes import get_cluster_pod_logs

    args = args or {}
    try:
        logs = get_cluster_pod_logs(args.get("namespace", ""), args.get("pod", ""),
                                    args.get("container") or None, bool(args.get("previous")))
    except RuntimeError as exc:
        return {"erro": str(exc)}
    lines = logs.splitlines()[-120:]
    return {"linhas": len(lines), "logs": "\n".join(lines)}


def tool_recommendations(args, _ctx):
    from approval.gate import list_by_status

    _, items = list_by_status((args or {}).get("status"))
    return {"total": len(items), "recomendacoes": [
        {"id": i["id"], "tipo": i["type"], "severidade": i["severity"], "status": i["status"],
         "alvo": i.get("pool"), "acao": i.get("action"), "confianca": i.get("confidence")}
        for i in items[:40]]}


def tool_scheduling(args, _ctx):
    report = _latest_report()
    if not report:
        return {"erro": "Nenhuma avaliação ainda"}
    findings = report.get("scheduling", {}).get("top_findings", [])
    namespace = (args or {}).get("namespace")
    if namespace:
        findings = [f for f in findings if f.get("namespace") == namespace]
    return {"causas": report.get("scheduling", {}).get("causes"), "achados": findings[:30]}


def tool_node_details(args, _ctx):
    from analyzers.node_detail import build_node_detail

    name = (args or {}).get("node")
    if not name:
        return {"erro": "Informe o node"}
    if current_cluster_mode.get() == "agent":
        from approval.store import load_cluster_snapshot

        snap = load_cluster_snapshot() or {}
        nodes, pods = snap.get("nodes") or {"items": []}, snap.get("pods") or {"items": []}
        node_metrics, pod_metrics = snap.get("node_metrics") or {}, snap.get("pod_metrics") or {}
    else:
        from collectors.kubernetes import get_nodes, get_pods
        from collectors.metrics import get_node_metrics, get_pod_metrics

        nodes, pods, node_metrics, pod_metrics = get_nodes(), get_pods(), get_node_metrics(), get_pod_metrics()
    detail = build_node_detail(name, nodes, pods, node_metrics, pod_metrics)
    if not detail:
        return {"erro": f"Node {name} não encontrado"}
    detail["pods"] = detail["pods"][:40]
    return detail


TOOLS = {
    "resumo_cluster": (tool_cluster_summary,
                       "Resumo da última avaliação: nodes, pods, saúde das métricas, decisão, consumo por node.",
                       {}),
    "pods_com_problema": (tool_problem_pods,
                          "Lista pods que não estão saudáveis (não Running, com reinícios ou não prontos).",
                          {"namespace": {"type": "string", "description": "Filtrar por namespace (opcional)"}}),
    "detalhes_pod": (tool_pod_details,
                     "Status detalhado de um pod: containers, último estado (ex.: OOMKilled), requests/limits e eventos.",
                     {"namespace": {"type": "string"}, "pod": {"type": "string"}}),
    "logs_pod": (tool_pod_logs,
                 "Últimas linhas de log de um container (use previous=true para a execução anterior a um crash).",
                 {"namespace": {"type": "string"}, "pod": {"type": "string"},
                  "container": {"type": "string"}, "previous": {"type": "boolean"}}),
    "detalhes_node": (tool_node_details,
                      "Detalhe de um node: capacidade, uso, taints, condições e pods que rodam nele (uso x requests).",
                      {"node": {"type": "string"}}),
    "recomendacoes": (tool_recommendations,
                      "Recomendações atuais da ferramenta (capacity, rightsizing, scheduling) e seus status.",
                      {"status": {"type": "string", "enum": ["pending", "approved", "rejected", "executed", "failed"]}}),
    "achados_scheduling": (tool_scheduling,
                           "Causas e achados de problemas de agendamento (Pending, imagem, PVC, secret, recursos).",
                           {"namespace": {"type": "string"}}),
}
REQUIRED = {"detalhes_pod": ["namespace", "pod"], "logs_pod": ["namespace", "pod"], "detalhes_node": ["node"]}


def tool_schemas():
    return [
        {"name": name, "description": desc,
         "input_schema": {"type": "object", "properties": props, "required": REQUIRED.get(name, [])}}
        for name, (_, desc, props) in TOOLS.items()
    ]


def run_tool(name, args, ctx):
    from assistant.redact import redact

    if name not in TOOLS:
        return json.dumps({"erro": f"Ferramenta desconhecida: {name}"})
    try:
        result = TOOLS[name][0](args or {}, ctx)
    except Exception as exc:  # nunca derrubar a conversa
        result = {"erro": f"Falha ao consultar: {exc}"}
    text = json.dumps(result, ensure_ascii=False, default=str)
    text = redact(text)
    if len(text) > MAX_RESULT_CHARS:
        text = text[:MAX_RESULT_CHARS] + "… [truncado]"
    return text
