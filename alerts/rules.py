"""Regras de alerta a partir do relatório de avaliação."""

UNHEALTHY_STATUSES = {
    "CrashLoopBackOff", "OOMKilled", "Error", "ImagePullBackOff", "ErrImagePull",
    "CreateContainerConfigError", "CreateContainerError", "InvalidImageName",
}
NODE_MEM_HIGH = 90
NODE_CPU_HIGH = 90
SEVERITY_RANK = {"LOW": 1, "MEDIUM": 2, "HIGH": 3}


def unhealthy_pods(pods):
    from collectors.kubernetes import parse_cluster_pods

    return [p for p in parse_cluster_pods(pods) if p["status"] in UNHEALTHY_STATUSES]


def build_alerts(report):
    alerts = []

    def add(key, severity, title, detail):
        alerts.append({"key": key, "severity": severity, "title": title, "detail": detail})

    for node in report.get("nodes_usage", []) or []:
        if not node.get("ready"):
            add(f"node-notready:{node['name']}", "HIGH", f"Node {node['name']} NotReady",
                f"Pool {node.get('pool')}: o node não está pronto; pods podem estar sendo despejados.")
        mem = node.get("mem_usage_pct")
        if mem is not None and mem >= NODE_MEM_HIGH:
            add(f"node-mem:{node['name']}", "HIGH", f"Memória do node {node['name']} em {mem}%",
                f"Uso real de memória acima de {NODE_MEM_HIGH}% (reservado: {node.get('mem_req_pct')}%). "
                "Risco de OOMKill e eviction.")
        cpu = node.get("cpu_usage_pct")
        if cpu is not None and cpu >= NODE_CPU_HIGH:
            add(f"node-cpu:{node['name']}", "MEDIUM", f"CPU do node {node['name']} em {cpu}%",
                "Uso real de CPU muito alto; latência e throttling prováveis.")

    for pod in report.get("unhealthy_pods", []) or []:
        add(f"pod:{pod['namespace']}/{pod['name']}", "HIGH",
            f"Pod {pod['namespace']}/{pod['name']} em {pod['status']}",
            f"Reinícios: {pod.get('restarts', 0)}. Abra o Assistente IA ou os logs para o diagnóstico.")

    pending = (report.get("summary") or {}).get("pending_pods", 0)
    if pending:
        causes = (report.get("scheduling") or {}).get("causes", {})
        labels = {"INSUFFICIENT_MEMORY": "memória insuficiente", "INSUFFICIENT_CPU": "CPU insuficiente",
                  "PVC": "volume (PVC)", "TAINT": "taint sem toleration", "AFFINITY": "regra de afinidade",
                  "NODE_SELECTOR": "nodeSelector sem node compatível"}
        top = ", ".join(f"{labels.get(k, k.replace('_', ' ').lower())} ({v})"
                        for k, v in sorted(causes.items(), key=lambda i: -i[1])[:3])
        add("pods-pending", "MEDIUM", f"{pending} pod(s) Pending", f"Causas principais: {top or 'ver Scheduling'}.")

    for rec in report.get("recommendations", []) or []:
        if rec.get("severity") == "HIGH" and rec.get("status") == "pending":
            add(f"rec:{rec['id']}", "HIGH", f"Recomendação crítica: {rec.get('type')}", rec.get("action", "")[:400])

    for reason in (report.get("decision") or {}).get("reasons", []):
        if "desatualizados" in reason:
            add("agent-stale", "HIGH", "Coletor do cluster sem enviar dados", reason)
    return alerts


def filter_by_severity(alerts, min_severity):
    floor = SEVERITY_RANK.get(min_severity or "MEDIUM", 2)
    return [a for a in alerts if SEVERITY_RANK.get(a["severity"], 0) >= floor]
