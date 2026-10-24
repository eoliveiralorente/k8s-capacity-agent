"""Avalia alertas após cada avaliação e envia aos canais configurados."""
import logging
import os
import threading

from tenant_context import current_cluster_id, current_cluster_mode, current_cluster_name, current_tenant_id

log = logging.getLogger("capacity-agent.alerts")
REMIND_HOURS = int(os.getenv("CAPACITY_AGENT_ALERT_REMIND_HOURS", "6"))


def _ai_explain(tenant_id, item):
    """Uma explicação curta da IA para o alerta mais grave (no máximo 1 chamada por envio)."""
    from accounts.store import get_assistant_config
    from assistant.engine import AssistantError, ask

    config = get_assistant_config(tenant_id, include_key=True)
    if not config or not config.get("enabled"):
        return None
    question = (f"Alerta: {item['title']}. {item.get('detail', '')} "
                "Em no máximo 3 linhas: causa provável e primeiro passo para resolver.")
    try:
        answer, _ = ask(config, [{"role": "user", "content": question}], {"role": "operador"})
        return answer[:600]
    except AssistantError as exc:
        log.warning("IA indisponível para o alerta: %s", exc)
        return None


def process_alerts(report, send=True):
    """Calcula, deduplica e envia. Retorna os itens notificados (para testes e auditoria)."""
    from accounts.store import get_alert_settings
    from alerts.notify import deliver
    from alerts.rules import build_alerts, filter_by_severity
    from approval.store import append_audit, reconcile_alert_state
    from licensing.core import has_feature

    tenant_id = current_tenant_id.get()
    if not has_feature("alerts"):
        return []
    config = (get_alert_settings(tenant_id, include_secrets=True) if tenant_id else None) or {}
    if config and not config.get("enabled", True):
        return []
    alerts = filter_by_severity(build_alerts(report), config.get("min_severity"))
    items = reconcile_alert_state(alerts, remind_hours=REMIND_HOURS)
    if not items or not send:
        return items
    if config.get("include_ai") and has_feature("ai_assistant"):
        first_new = next((i for i in items if i["state"] == "new" and i["severity"] == "HIGH"), None)
        if first_new:
            first_new["ai"] = _ai_explain(tenant_id, first_new)
    channels = any(config.get(k) for k in ("slack_url", "teams_url", "webhook_url", "emails"))
    results = deliver(config, report.get("cluster") or current_cluster_name.get() or "cluster",
                      items, os.getenv("CAPACITY_AGENT_PUBLIC_URL")) if channels else {}
    append_audit("alerts_sent", {"count": len(items), "results": results,
                                 "keys": [f"{i['state']}:{i['key']}" for i in items][:20]})
    return items


def process_alerts_async(report):
    """Dispara em segundo plano para não atrasar a resposta da avaliação."""
    context = (current_tenant_id.get(), current_cluster_id.get(), current_cluster_name.get(), current_cluster_mode.get())

    def run():
        tokens = [current_tenant_id.set(context[0]), current_cluster_id.set(context[1]),
                  current_cluster_name.set(context[2]), current_cluster_mode.set(context[3])]
        try:
            process_alerts(report)
        except Exception as exc:  # alerta nunca derruba a avaliação
            log.warning("Falha ao processar alertas: %s", exc)
        finally:
            for var, tok in zip([current_cluster_mode, current_cluster_name, current_cluster_id, current_tenant_id],
                                reversed(tokens)):
                var.reset(tok)

    threading.Thread(target=run, name="alerts", daemon=True).start()
