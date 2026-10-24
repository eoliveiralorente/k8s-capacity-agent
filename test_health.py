from collectors.kubernetes import get_nodes, get_pods
from collectors.metrics import get_node_metrics, get_pod_metrics
from analyzers.health import analyze_health


print("=" * 80)
print("TESTE — HEALTH ANALYZER")
print("=" * 80)

nodes = get_nodes()
pods = get_pods()

node_metrics = get_node_metrics()
pod_metrics = get_pod_metrics()

health = analyze_health(
    nodes,
    pods,
    node_metrics,
    pod_metrics,
)

print()
print("CLUSTER HEALTH")
print("-" * 80)

print(
    f"Nodes................: "
    f"{health['total_nodes']}"
)

print(
    f"Pods Running..........: "
    f"{health['running_pods']}"
)

print(
    f"Pods Pending..........: "
    f"{health['pending_pods']}"
)

print(
    f"Node metrics.........: "
    f"{health['node_metrics']}"
)

print(
    f"Pod metrics..........: "
    f"{health['pod_metrics']}"
)

print()
print(
    f"Node coverage........: "
    f"{health['node_coverage_pct']}%"
)

print(
    f"Pod coverage.........: "
    f"{health['pod_coverage_pct']}%"
)

print()

for check in health["checks"]:

    print(
        f"[{check['status']}] "
        f"{check['name']} - "
        f"{check['message']}"
    )

print()
print(
    "DECISION LEVEL.......: "
    f"{health['decision_level']}"
)

print(
    "EXECUTION ALLOWED....: "
    f"{health['decision_allowed']}"
)

print()
print("=" * 80)
