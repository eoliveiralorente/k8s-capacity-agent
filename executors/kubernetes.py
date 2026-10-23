"""Execução nível 1: ações via API do Kubernetes (qualquer cloud).

Usa o kubeconfig do cluster ativo (cifrado por empresa), sem shell.
`dry_run=True` roda `--dry-run=server`: o próprio cluster valida a mudança.
"""
import re
import subprocess

from collectors.kubernetes import _run_process

NAME_RE = re.compile(r"[a-z0-9](?:[-a-z0-9.]*[a-z0-9])?")
CPU_RE = re.compile(r"\d+m")
MEM_RE = re.compile(r"\d+Mi")
KINDS = {"Deployment": "deployment", "StatefulSet": "statefulset", "DaemonSet": "daemonset"}


def _validate(params):
    for field in ("namespace", "name", "container"):
        value = params.get(field, "")
        if len(value) > 253 or not NAME_RE.fullmatch(value):
            raise ValueError(f"Valor inválido em {field}: {value!r}")
    if params.get("kind") not in KINDS:
        raise ValueError(f"Tipo de workload não suportado: {params.get('kind')}")
    target = params.get("target", {})
    if not CPU_RE.fullmatch(target.get("cpu", "")) or not MEM_RE.fullmatch(target.get("memory", "")):
        raise ValueError("Valores de requests inválidos")


def _set_resources_args(params, cpu, memory, dry_run):
    args = [
        "kubectl", "set", "resources",
        f"{KINDS[params['kind']]}/{params['name']}",
        "--namespace", params["namespace"],
        "--containers", params["container"],
        f"--requests=cpu={cpu},memory={memory}",
        "-o", "name",
    ]
    if dry_run:
        args.append("--dry-run=server")
    return args


def execute_set_resources(operation, dry_run=False):
    params = operation.get("params", {})
    try:
        _validate(params)
    except ValueError as exc:
        return {"success": False, "dry_run": dry_run, "output": str(exc)}

    target = params["target"]
    args = _set_resources_args(params, target["cpu"], target["memory"], dry_run)
    command = " ".join(args)

    try:
        result = _run_process(args, capture_output=True, text=True, timeout=60)
    except subprocess.TimeoutExpired:
        return {"success": False, "dry_run": dry_run, "output": "Tempo esgotado", "command": command}
    except OSError as exc:
        return {"success": False, "dry_run": dry_run, "output": f"Falha ao executar: {exc}", "command": command}

    output = "\n".join(p for p in (result.stdout.strip(), result.stderr.strip()) if p)
    response = {
        "success": result.returncode == 0,
        "dry_run": dry_run,
        "returncode": result.returncode,
        "output": (("Validado pelo cluster (dry-run): " if dry_run and result.returncode == 0 else "") + output)[:4000],
        "command": command,
    }

    current = params.get("current", {})
    if current.get("cpu") and current.get("memory"):
        response["rollback_command"] = " ".join(
            _set_resources_args(params, current["cpu"], current["memory"], dry_run=False)
        )
    else:
        response["rollback_command"] = (
            "Request anterior não estava definido; para reverter, edite o manifesto do workload "
            "(ou o repositório GitOps) removendo o request."
        )
    return response
