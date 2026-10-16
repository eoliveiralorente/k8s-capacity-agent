import json
import os
import subprocess
import tempfile
from contextlib import contextmanager
from pathlib import Path

from config import KUBECONFIG
from tenant_context import current_cluster_id, current_tenant_id


@contextmanager
def _command_env():
    env = os.environ.copy()
    tenant_id = current_tenant_id.get()
    cluster_id = current_cluster_id.get()
    if tenant_id and cluster_id:
        from accounts.store import decrypt_cluster_kubeconfig

        kubeconfig = decrypt_cluster_kubeconfig(tenant_id, cluster_id)
        if kubeconfig:
            with tempfile.TemporaryDirectory(prefix="capacity-kubeconfig-") as temp_dir:
                config_path = Path(temp_dir) / "config"
                config_path.write_bytes(kubeconfig)
                config_path.chmod(0o600)
                env["KUBECONFIG"] = str(config_path)
                yield env
                return
    if KUBECONFIG:
        env["KUBECONFIG"] = KUBECONFIG
    yield env


def _run_process(command, **kwargs):
    with _command_env() as env:
        return subprocess.run(command, env=env, **kwargs)
    return env


def get_current_context():
    result = _run_process(
        ["kubectl", "config", "current-context"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or "Contexto Kubernetes indisponível"
        raise RuntimeError(detail)
    return result.stdout.strip()


def run(command):
    result = _run_process(
        command,
        shell=True,
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        return ""

    return result.stdout.strip()


def get_cluster_overview():
    context = get_current_context()
    nodes_result = _run_process(
        ["kubectl", "get", "nodes", "-o", "json"],
        capture_output=True,
        text=True,
    )
    if nodes_result.returncode != 0:
        detail = nodes_result.stderr.strip() or "Não foi possível consultar os nodes"
        raise RuntimeError(detail)

    node_data = json.loads(nodes_result.stdout)
    nodes = []
    for node in node_data.get("items", []):
        metadata = node.get("metadata", {})
        status = node.get("status", {})
        labels = metadata.get("labels", {})
        roles = sorted(
            label.removeprefix("node-role.kubernetes.io/")
            for label in labels
            if label.startswith("node-role.kubernetes.io/")
        ) or ["worker"]
        ready = next(
            (condition.get("status") == "True"
             for condition in status.get("conditions", [])
             if condition.get("type") == "Ready"),
            False,
        )
        nodes.append({
            "name": metadata.get("name", ""),
            "status": "Ready" if ready else "NotReady",
            "roles": roles,
            "version": status.get("nodeInfo", {}).get("kubeletVersion", "—"),
        })

    return {
        "context": context,
        "nodes": nodes,
        "kubeconfig_configured": bool(KUBECONFIG),
    }


def get_nodes():
    output = run("kubectl get nodes -o json")

    if not output:
        return {"items": []}

    return json.loads(output)


def get_pods():
    output = run("kubectl get pods -A -o json")

    if not output:
        return {"items": []}

    return json.loads(output)


def get_cluster_pods():
    result = _run_process(
        ["kubectl", "get", "pods", "--all-namespaces", "-o", "json"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or "Não foi possível consultar os pods"
        raise RuntimeError(detail)

    pod_data = json.loads(result.stdout)
    pods = []
    for item in pod_data.get("items", []):
        metadata = item.get("metadata", {})
        spec = item.get("spec", {})
        status_data = item.get("status", {})
        container_statuses = status_data.get("containerStatuses", [])
        init_statuses = status_data.get("initContainerStatuses", [])
        waiting_reasons = [
            container.get("state", {}).get("waiting", {}).get("reason")
            for container in [*init_statuses, *container_statuses]
            if container.get("state", {}).get("waiting", {}).get("reason")
        ]
        if metadata.get("deletionTimestamp"):
            pod_status = "Terminating"
        elif waiting_reasons:
            pod_status = waiting_reasons[0]
        elif status_data.get("phase") == "Succeeded":
            pod_status = "Completed"
        else:
            pod_status = status_data.get("phase", "Unknown")

        pods.append({
            "namespace": metadata.get("namespace", "default"),
            "name": metadata.get("name", ""),
            "ready": (
                f"{sum(bool(container.get('ready')) for container in container_statuses)}"
                f"/{len(spec.get('containers', []))}"
            ),
            "status": pod_status,
            "restarts": sum(
                container.get("restartCount", 0)
                for container in [*init_statuses, *container_statuses]
            ),
            "created_at": metadata.get("creationTimestamp"),
        })

    return pods


def get_cluster_events():
    output = run(
        "kubectl get events -A "
        "--sort-by=.lastTimestamp "
        "-o json"
    )

    if not output:
        return {"items": []}

    return json.loads(output)