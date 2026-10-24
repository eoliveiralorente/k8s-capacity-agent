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



SCALE_KINDS = {"Deployment": "deployment", "StatefulSet": "statefulset"}


def _run_k8s(args, dry_run, rollback=None):
    command = " ".join(args)
    try:
        result = _run_process(args, capture_output=True, text=True, timeout=60)
    except subprocess.TimeoutExpired:
        return {"success": False, "dry_run": dry_run, "output": "Tempo esgotado", "command": command}
    except OSError as exc:
        return {"success": False, "dry_run": dry_run, "output": f"Falha ao executar: {exc}", "command": command}
    output = "\n".join(p for p in (result.stdout.strip(), result.stderr.strip()) if p)
    response = {"success": result.returncode == 0, "dry_run": dry_run, "returncode": result.returncode,
                "output": (("Validado pelo cluster (dry-run): " if dry_run and result.returncode == 0 else "") + output)[:4000],
                "command": command}
    if rollback:
        response["rollback_command"] = rollback
    return response


def _check_names(params, *fields):
    for field in fields:
        value = str(params.get(field, ""))
        if len(value) > 253 or not NAME_RE.fullmatch(value):
            raise ValueError(f"Valor inválido em {field}: {value!r}")
    if params.get("kind") not in SCALE_KINDS:
        raise ValueError(f"Tipo de workload não suportado: {params.get('kind')}")


def _int_param(params, field, low=0, high=1000):
    value = params.get(field)
    if not isinstance(value, int) or not low <= value <= high:
        raise ValueError(f"Valor inválido em {field}: {value!r}")
    return value


def execute_scale(operation, dry_run=False):
    params = operation.get("params", {})
    try:
        _check_names(params, "namespace", "name")
        target = _int_param(params, "target_replicas", 0)
        current = _int_param(params, "current_replicas", 0)
    except ValueError as exc:
        return {"success": False, "dry_run": dry_run, "output": str(exc)}
    ref = f"{SCALE_KINDS[params['kind']]}/{params['name']}"
    args = ["kubectl", "scale", ref, "--namespace", params["namespace"], f"--replicas={target}",
            f"--current-replicas={current}", "-o", "name"]
    if dry_run:
        args.append("--dry-run=server")
    rollback = f"kubectl scale {ref} --namespace {params['namespace']} --replicas={current}"
    return _run_k8s(args, dry_run, rollback)


def execute_create_hpa(operation, dry_run=False):
    params = operation.get("params", {})
    try:
        _check_names(params, "namespace", "name")
        low = _int_param(params, "min_replicas", 1)
        high = _int_param(params, "max_replicas", 1)
        cpu = _int_param(params, "cpu_percent", 10, 100)
        if high < low:
            raise ValueError("max_replicas menor que min_replicas")
    except ValueError as exc:
        return {"success": False, "dry_run": dry_run, "output": str(exc)}
    ref = f"{SCALE_KINDS[params['kind']]}/{params['name']}"
    args = ["kubectl", "autoscale", ref, "--namespace", params["namespace"], f"--min={low}", f"--max={high}",
            f"--cpu-percent={cpu}", "-o", "name"]
    if dry_run:
        args.append("--dry-run=server")
    rollback = f"kubectl delete hpa {params['name']} --namespace {params['namespace']}"
    return _run_k8s(args, dry_run, rollback)


def execute_patch_hpa_max(operation, dry_run=False):
    import json as jsonlib

    params = operation.get("params", {})
    try:
        _check_names(params, "namespace", "name", "hpa")
        target = _int_param(params, "target_max", 1)
        current = _int_param(params, "current_max", 1)
    except ValueError as exc:
        return {"success": False, "dry_run": dry_run, "output": str(exc)}
    args = ["kubectl", "patch", "hpa", params["hpa"], "--namespace", params["namespace"], "--type=merge",
            "-p", jsonlib.dumps({"spec": {"maxReplicas": target}}), "-o", "name"]
    if dry_run:
        args.append("--dry-run=server")
    rollback = (f"kubectl patch hpa {params['hpa']} --namespace {params['namespace']} --type=merge "
                f"-p '{{\"spec\":{{\"maxReplicas\":{current}}}}}'")
    return _run_k8s(args, dry_run, rollback)


K8S_EXECUTORS = {
    "k8s_set_resources": execute_set_resources,
    "k8s_scale": execute_scale,
    "k8s_create_hpa": execute_create_hpa,
    "k8s_patch_hpa_max": execute_patch_hpa_max,
}
