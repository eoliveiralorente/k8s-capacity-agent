import subprocess

from config import KUBERNETES_PROVIDER
from collectors.kubernetes import _run_process
from tenant_context import current_cluster_provider, current_tenant_id


def execute_scale_node_pool(operation, dry_run=False):

    args = operation.get("execute_args")
    command = operation.get("execute_command")

    if not args:
        return {
            "success": False,
            "output": "Comando de execução não definido (gere uma nova avaliação)",
        }

    if dry_run:
        return {
            "success": True,
            "dry_run": True,
            "output": operation.get("dry_run_command", command),
        }

    try:
        result = _run_process(args, capture_output=True, text=True, timeout=600)
    except subprocess.TimeoutExpired:
        return {"success": False, "dry_run": False, "output": "Tempo esgotado no resize", "command": command}
    except OSError as exc:
        return {"success": False, "dry_run": False, "output": f"Falha ao executar: {exc}", "command": command}

    output = "\n".join(part for part in (result.stdout.strip(), result.stderr.strip()) if part)

    return {
        "success": result.returncode == 0,
        "dry_run": False,
        "returncode": result.returncode,
        "output": output[:4000] or "Comando executado (sem output)",
        "command": command,
    }


def execute_operation(operation, dry_run=False):

    from executors.kubernetes import K8S_EXECUTORS

    if operation.get("kind") in K8S_EXECUTORS:
        # Nível 1: API do Kubernetes com o kubeconfig/ServiceAccount do cluster ativo — qualquer cloud.
        return K8S_EXECUTORS[operation["kind"]](operation, dry_run=dry_run)

    if current_tenant_id.get():
        return {
            "success": False,
            "output": "Execução automática desabilitada no modo multiempresa",
        }

    provider = current_cluster_provider.get() or KUBERNETES_PROVIDER
    if provider != "gke":
        return {
            "success": False,
            "output": "Execução automática indisponível fora do modo GKE",
        }

    kind = operation.get("kind")

    if kind == "scale_node_pool":
        return execute_scale_node_pool(operation, dry_run=dry_run)

    return {
        "success": False,
        "output": f"Operação '{kind}' não suportada para execução automática",
    }
