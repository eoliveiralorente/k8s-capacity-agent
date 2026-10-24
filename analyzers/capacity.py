from collections import defaultdict

from analyzers.providers import is_control_plane, node_pool
from collectors.metrics import parse_cpu, parse_memory


def pct(numerator, denominator):

    if not denominator:
        return 0.0

    return round(
        numerator / denominator * 100,
        1
    )


def empty_bucket():

    return {
        "cpu_allocatable": 0,
        "mem_allocatable": 0,
        "cpu_requests": 0,
        "mem_requests": 0,
        "cpu_limits": 0,
        "mem_limits": 0,
        "cpu_usage": 0,
        "mem_usage": 0,
        "pod_count": 0,
        "node_count": 0,
    }


def add(bucket, **values):

    for key, value in values.items():
        bucket[key] += value


def metrics(bucket):

    return {
        "cpu_req_vs_alloc_pct":
            pct(
                bucket["cpu_requests"],
                bucket["cpu_allocatable"]
            ),

        "mem_req_vs_alloc_pct":
            pct(
                bucket["mem_requests"],
                bucket["mem_allocatable"]
            ),

        "cpu_usage_vs_alloc_pct":
            pct(
                bucket["cpu_usage"],
                bucket["cpu_allocatable"]
            ),

        "mem_usage_vs_alloc_pct":
            pct(
                bucket["mem_usage"],
                bucket["mem_allocatable"]
            ),

        "cpu_usage_vs_req_pct":
            pct(
                bucket["cpu_usage"],
                bucket["cpu_requests"]
            ),

        "mem_usage_vs_req_pct":
            pct(
                bucket["mem_usage"],
                bucket["mem_requests"]
            ),
    }


def analyze_capacity(nodes, pods, node_metrics, pod_metrics):
    """
    Analisa a capacidade atual do cluster.

    Esta função é READ ONLY.

    Não executa:
      - kubectl scale
      - kubectl patch
      - gcloud resize
      - delete
      - alteração de deployment

    Retorna informações agregadas por node pool.
    """

    # ------------------------------------------------------------
    # NODE INFORMATION
    # ------------------------------------------------------------

    node_info = {}

    pool_buckets = defaultdict(empty_bucket)
    pool_metadata = defaultdict(lambda: {
        "ready_nodes": 0,
        "machine_types": set(),
        "versions": set(),
        "control_plane": False,
    })

    for node in nodes.get("items", []):

        metadata = node.get("metadata", {})
        status = node.get("status", {})

        name = metadata.get("name", "-")

        labels = metadata.get("labels", {})

        role_labels = sorted(
            label.split("/", 1)[1]
            for label in labels
            if label.startswith("node-role.kubernetes.io/")
        )
        role = labels.get("magnum.openstack.org/role") or (role_labels[0] if role_labels else "worker")
        pool = node_pool(labels, fallback=role)

        machine = labels.get(
            "node.kubernetes.io/instance-type",
            labels.get("beta.kubernetes.io/instance-type", "-"),
        )
        kubelet_version = status.get("nodeInfo", {}).get("kubeletVersion", "-")
        ready = any(
            condition.get("type") == "Ready" and condition.get("status") == "True"
            for condition in status.get("conditions", [])
        )

        allocatable = status.get(
            "allocatable",
            {}
        )

        cpu_alloc = parse_cpu(
            allocatable.get("cpu", "0")
        )

        mem_alloc = parse_memory(
            allocatable.get("memory", "0")
        )

        node_info[name] = {
            "pool": pool,
            "machine": machine,
            "ready": ready,
            "cpu_allocatable": cpu_alloc,
            "mem_allocatable": mem_alloc,
        }

        add(
            pool_buckets[pool],

            cpu_allocatable=cpu_alloc,
            mem_allocatable=mem_alloc,

            node_count=1,
        )
        metadata_bucket = pool_metadata[pool]
        metadata_bucket["ready_nodes"] += int(ready)
        if is_control_plane(labels):
            metadata_bucket["control_plane"] = True
        if machine and machine != "-":
            metadata_bucket["machine_types"].add(machine)
        if kubelet_version and kubelet_version != "-":
            metadata_bucket["versions"].add(kubelet_version)

    # ------------------------------------------------------------
    # POD METRICS
    # ------------------------------------------------------------

    for pod in pods.get("items", []):

        metadata = pod.get(
            "metadata",
            {}
        )

        namespace = metadata.get(
            "namespace",
            "-"
        )

        name = metadata.get(
            "name",
            "-"
        )

        phase = pod.get(
            "status",
            {}
        ).get(
            "phase",
            "-"
        )

        if phase not in (
            "Running",
            "Pending",
        ):
            continue

        node_name = pod.get(
            "spec",
            {}
        ).get(
            "nodeName"
        )

        if not node_name:
            continue

        node = node_info.get(node_name)

        if not node:
            continue

        pool = node["pool"]

        cpu_request = 0
        mem_request = 0

        cpu_limit = 0
        mem_limit = 0

        for container in pod.get(
            "spec",
            {}
        ).get(
            "containers",
            []
        ):

            resources = container.get(
                "resources",
                {}
            )

            requests = resources.get(
                "requests",
                {}
            )

            limits = resources.get(
                "limits",
                {}
            )

            cpu_request += parse_cpu(
                requests.get(
                    "cpu",
                    "0"
                )
            )

            mem_request += parse_memory(
                requests.get(
                    "memory",
                    "0"
                )
            )

            cpu_limit += parse_cpu(
                limits.get(
                    "cpu",
                    "0"
                )
            )

            mem_limit += parse_memory(
                limits.get(
                    "memory",
                    "0"
                )
            )

        # --------------------------------------------------------
        # USAGE
        # --------------------------------------------------------

        key = f"{namespace}/{name}"

        usage = pod_metrics.get(
            key,
            {}
        )

        cpu_usage = usage.get(
            "cpu_m",
            0
        )

        mem_usage = usage.get(
            "mem_b",
            0
        )

        add(
            pool_buckets[pool],

            cpu_requests=cpu_request,
            mem_requests=mem_request,

            cpu_limits=cpu_limit,
            mem_limits=mem_limit,

            cpu_usage=cpu_usage,
            mem_usage=mem_usage,

            pod_count=1,
        )

    # ------------------------------------------------------------
    # RESULT
    # ------------------------------------------------------------

    result = {}

    for pool_name in sorted(
        pool_buckets.keys()
    ):

        bucket = pool_buckets[
            pool_name
        ]

        calculated_metrics = metrics(
            bucket
        )

        result[pool_name] = {
            "pool": pool_name,

            "capacity": bucket,
            "control_plane": pool_metadata[pool_name]["control_plane"],

            "metrics": calculated_metrics,
            "kubernetes": {
                "status": (
                    "Ready" if pool_metadata[pool_name]["ready_nodes"] == bucket["node_count"]
                    else "Degraded" if pool_metadata[pool_name]["ready_nodes"]
                    else "NotReady"
                ),
                "version": ", ".join(sorted(pool_metadata[pool_name]["versions"])) or "—",
                "machine_type": ", ".join(sorted(pool_metadata[pool_name]["machine_types"])) or "—",
            },
        }

    return result