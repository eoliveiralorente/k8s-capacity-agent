"""Pacote de suporte: um .zip SEM segredos para o cliente enviar no chamado.

Inclui: versão, saúde, licença (sem o arquivo), variáveis CAPACITY_AGENT_* não
sensíveis, últimas linhas de log, auditoria recente e resumo da última avaliação.
NÃO inclui: banco de dados, chaves, kubeconfigs, tokens, URLs de webhook, logs de pods.
Tudo passa pelo mascaramento de dados sensíveis.
"""
import io
import json
import os
import platform
import zipfile
from datetime import datetime, timezone

from assistant.redact import redact, redact_obj

SENSITIVE_WORDS = ("KEY", "PASSWORD", "TOKEN", "SECRET", "LICENSE")


def _safe_env():
    env = {}
    for name, value in sorted(os.environ.items()):
        if not name.startswith("CAPACITY_AGENT_"):
            continue
        env[name] = "[OCULTO]" if any(w in name for w in SENSITIVE_WORDS) else redact(value)
    return env


def build_bundle():
    from licensing.core import license_status
    from support.health import run_checks
    from support.logbuffer import recent_lines
    from version import VERSION

    files = {
        "LEIA-ME.txt": (
            "Pacote de suporte do Capacity Agent.\n"
            "Não contém banco de dados, chaves, kubeconfigs, tokens nem logs de aplicações.\n"
            f"Gerado em {datetime.now(timezone.utc).isoformat()} — versão {VERSION}.\n"
        ),
        "health.json": run_checks(),
        "license.json": {k: v for k, v in license_status().items() if k not in ("customer",)},
        "environment.json": {"python": platform.python_version(), "platform": platform.platform(),
                             "variables": _safe_env()},
        "logs.txt": "\n".join(redact(line) for line in recent_lines()),
    }
    try:
        from approval.store import load_audit
        files["audit.json"] = redact_obj(load_audit(limit=200))
    except Exception as exc:
        files["audit.json"] = {"erro": str(exc)}
    try:
        from approval.store import load_latest_report
        from engine.evaluation import summarize_report_for_api
        report = load_latest_report()
        if report:
            summary = summarize_report_for_api(report)
            files["last_evaluation.json"] = redact_obj({
                "created_at": summary.get("created_at"), "summary": summary.get("summary"),
                "health": summary.get("health"), "decision": summary.get("decision"),
                "nodes_usage": summary.get("nodes_usage"),
                "recommendations": [{"type": r.get("type"), "severity": r.get("severity"), "status": r.get("status"),
                                     "operation_kind": (r.get("operation") or {}).get("kind")}
                                    for r in summary.get("recommendations", [])],
            })
    except Exception as exc:
        files["last_evaluation.json"] = {"erro": str(exc)}

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in files.items():
            data = content if isinstance(content, str) else json.dumps(content, ensure_ascii=False, indent=2, default=str)
            archive.writestr(name, data)
    return buffer.getvalue()
