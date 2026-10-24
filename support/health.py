"""Diagnóstico da instalação (página de saúde e pacote de suporte)."""
import os
import shutil
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

from version import VERSION

STARTED_AT = time.time()


def _check(name, ok, detail, hint=None, level=None):
    return {"name": name, "status": level or ("ok" if ok else "erro"), "detail": detail, "hint": hint}


def _kubectl(args, timeout=15):
    from collectors.kubernetes import _run_process

    try:
        result = _run_process(["kubectl", *args], capture_output=True, text=True, timeout=timeout)
        return result.returncode == 0, (result.stdout or result.stderr).strip()[:400]
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, str(exc)


def run_checks(include_cluster=True):
    from accounts import store as account_store
    from config import STATE_DIR
    from licensing.core import license_status
    from tenant_context import current_cluster_id, current_cluster_mode

    checks = []
    db = Path(account_store.DB_PATH)
    checks.append(_check("Banco de dados", db.is_file(), f"{db} ({db.stat().st_size // 1024} KB)" if db.is_file() else "não encontrado",
                         "Verifique o volume/PVC montado em /data"))
    try:
        Path(STATE_DIR).mkdir(parents=True, exist_ok=True)
        probe = Path(STATE_DIR) / ".write-test"
        probe.write_text("ok")
        probe.unlink()
        checks.append(_check("Gravação de estado", True, str(STATE_DIR)))
    except OSError as exc:
        checks.append(_check("Gravação de estado", False, str(exc), "Permissão do volume /data (usuário 10001)"))
    usage = shutil.disk_usage(db.parent if db.parent.exists() else "/")
    free_pct = round(usage.free / usage.total * 100, 1)
    checks.append(_check("Espaço em disco", free_pct > 10, f"{free_pct}% livre",
                         "Aumente o PVC (persistence.size)", None if free_pct > 10 else "aviso"))
    try:
        account_store._fernet()
        checks.append(_check("Chave de criptografia", True, "válida"))
    except RuntimeError as exc:
        checks.append(_check("Chave de criptografia", False, str(exc)[:200],
                             "Veja 'Chave de criptografia inválida' em Solução de problemas"))

    lic = license_status()
    checks.append(_check("Licença", lic["state"] in ("valid", "community"),
                         f"{lic['plan']} ({lic['state']}): {lic['message']}",
                         "Instale/renove a licença em Usuários → Licença",
                         None if lic["state"] in ("valid", "community") else "aviso"))

    ok, out = _kubectl(["version", "--client", "-o", "yaml"])
    checks.append(_check("kubectl", ok, out.splitlines()[1].strip() if ok and len(out.splitlines()) > 1 else out))

    from engine import sampler
    checks.append(_check("Coleta automática", sampler.SAMPLE_MINUTES > 0,
                         f"amostras a cada {sampler.SAMPLE_MINUTES} min; avaliação a cada {sampler.EVALUATE_MINUTES} min",
                         "CAPACITY_AGENT_SAMPLE_MINUTES / EVALUATE_MINUTES", None if sampler.SAMPLE_MINUTES > 0 else "aviso"))

    if include_cluster and current_cluster_id.get():
        if current_cluster_mode.get() == "agent":
            from approval.store import load_cluster_snapshot
            snap = load_cluster_snapshot()
            if snap:
                age = (datetime.now(timezone.utc) - datetime.fromisoformat(snap["_received_at"])).total_seconds() / 60
                checks.append(_check("Coletor (agente)", age < 60, f"último envio há {age:.0f} min",
                                     "kubectl -n capacity-agent logs deploy/capacity-collector", None if age < 60 else "erro"))
            else:
                checks.append(_check("Coletor (agente)", False, "nenhum envio recebido",
                                     "Confira panelUrl/token e a saída HTTPS do cluster"))
        else:
            ok, out = _kubectl(["get", "--raw", "/version"])
            checks.append(_check("API do cluster", ok, out[:160], "Kubeconfig/ServiceAccount e rede até a API"))
            ok, out = _kubectl(["top", "nodes", "--no-headers"])
            checks.append(_check("metrics-server", ok, f"{len(out.splitlines())} node(s) com métricas" if ok else out[:200],
                                 "Instale o metrics-server (kubectl top nodes precisa funcionar)"))
        from approval.store import list_reports
        reports = list_reports()
        last = reports[0]["created_at"] if reports else None
        checks.append(_check("Última avaliação", bool(last), last or "nenhuma", "Clique em Nova Avaliação",
                             None if last else "aviso"))

    worst = "erro" if any(c["status"] == "erro" for c in checks) else ("aviso" if any(c["status"] == "aviso" for c in checks) else "ok")
    return {
        "version": VERSION,
        "status": worst,
        "uptime_minutes": round((time.time() - STARTED_AT) / 60, 1),
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "checks": checks,
    }
