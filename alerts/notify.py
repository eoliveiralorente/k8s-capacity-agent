"""Envio de alertas: Slack, Microsoft Teams, webhook genérico e e-mail (SMTP)."""
import json
import os
import smtplib
import ssl
import urllib.error
import urllib.request
from email.message import EmailMessage

ICONS = {"HIGH": "🔴", "MEDIUM": "🟠", "LOW": "🟡", "RESOLVED": "✅"}


def _post_json(url, payload, timeout=15):
    request = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), method="POST",
                                     headers={"Content-Type": "application/json",
                                              "User-Agent": "capacity-agent-alerts/1"})
    context = ssl.create_default_context(cafile=os.getenv("CAPACITY_AGENT_CA_FILE") or None)
    with urllib.request.urlopen(request, timeout=timeout, context=context) as response:
        return response.status


def format_text(cluster, items, panel_url=None):
    lines = [f"Capacity Agent · cluster {cluster}"]
    for item in items:
        icon = ICONS.get("RESOLVED" if item.get("state") == "resolved" else item["severity"], "•")
        prefix = {"new": "NOVO", "reminder": "AINDA ATIVO", "resolved": "RESOLVIDO"}.get(item.get("state"), "")
        lines.append(f"{icon} [{prefix}] {item['title']}")
        if item.get("state") != "resolved" and item.get("detail"):
            lines.append(f"    {item['detail']}")
        if item.get("ai"):
            lines.append(f"    🤖 {item['ai']}")
    if panel_url:
        lines.append(f"Painel: {panel_url}")
    return "\n".join(lines)


def send_slack(url, text):
    return _post_json(url, {"text": text})


def send_teams(url, text):
    card = {"type": "AdaptiveCard", "version": "1.4", "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
            "body": [{"type": "TextBlock", "text": line, "wrap": True,
                      "weight": "Bolder" if i == 0 else "Default"} for i, line in enumerate(text.splitlines())]}
    return _post_json(url, {"type": "message", "attachments": [
        {"contentType": "application/vnd.microsoft.card.adaptive", "content": card}]})


def send_webhook(url, cluster, items):
    return _post_json(url, {"source": "capacity-agent", "cluster": cluster, "alerts": items})


def smtp_configured():
    return bool(os.getenv("CAPACITY_AGENT_SMTP_HOST") and os.getenv("CAPACITY_AGENT_SMTP_FROM"))


def send_email(recipients, subject, text):
    if not smtp_configured():
        raise RuntimeError("SMTP não configurado na instalação (CAPACITY_AGENT_SMTP_HOST/FROM)")
    message = EmailMessage()
    message["From"] = os.environ["CAPACITY_AGENT_SMTP_FROM"]
    message["To"] = ", ".join(recipients)
    message["Subject"] = subject
    message.set_content(text)
    host = os.environ["CAPACITY_AGENT_SMTP_HOST"]
    port = int(os.getenv("CAPACITY_AGENT_SMTP_PORT", "587"))
    with smtplib.SMTP(host, port, timeout=20) as smtp:
        if os.getenv("CAPACITY_AGENT_SMTP_STARTTLS", "true").lower() == "true":
            smtp.starttls(context=ssl.create_default_context())
        if os.getenv("CAPACITY_AGENT_SMTP_USER"):
            smtp.login(os.environ["CAPACITY_AGENT_SMTP_USER"], os.getenv("CAPACITY_AGENT_SMTP_PASSWORD", ""))
        smtp.send_message(message)


def deliver(config, cluster, items, panel_url=None):
    """Envia para todos os canais configurados. Retorna {canal: "ok" | "erro: ..."}."""
    text = format_text(cluster, items, panel_url)
    worst = "RESOLVED" if all(i.get("state") == "resolved" for i in items) else \
        max((i["severity"] for i in items if i.get("state") != "resolved"),
            key=lambda s: {"LOW": 1, "MEDIUM": 2, "HIGH": 3}.get(s, 0), default="MEDIUM")
    subject = f"{ICONS.get(worst, '')} Capacity Agent · {cluster}: {len(items)} alerta(s)"
    results = {}
    channels = [
        ("slack", config.get("slack_url"), lambda u: send_slack(u, text)),
        ("teams", config.get("teams_url"), lambda u: send_teams(u, text)),
        ("webhook", config.get("webhook_url"), lambda u: send_webhook(u, cluster, items)),
    ]
    for name, url, sender in channels:
        if not url:
            continue
        try:
            sender(url)
            results[name] = "ok"
        except (urllib.error.URLError, OSError, ValueError) as exc:
            results[name] = f"erro: {exc}"
    emails = [e.strip() for e in (config.get("emails") or "").split(",") if e.strip()]
    if emails:
        try:
            send_email(emails, subject, text)
            results["email"] = "ok"
        except (RuntimeError, OSError, smtplib.SMTPException) as exc:
            results["email"] = f"erro: {exc}"
    return results
