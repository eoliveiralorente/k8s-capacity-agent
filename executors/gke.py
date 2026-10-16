from collectors.kubernetes import run
from config import KUBERNETES_PROVIDER
from tenant_context import current_cluster_provider


def execute_scale_node_pool(operation, dry_run=False):

    command = operation.get("execute_command")

    if not command:
        return {
            "success": False,
            "output": "Comando de execução não definido",
        }

    if dry_run:
        return {
            "success": True,
            "dry_run": True,
            "output": operation.get("dry_run_command", command),
        }

    output = run(command)

    success = bool(output) or "Resizing" in output

    return {
        "success": success,
        "dry_run": False,
        "output": output or "Comando executado (sem output)",
        "command": command,
    }


def execute_operation(operation, dry_run=False):

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
