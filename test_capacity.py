from collectors.kubernetes import get_nodes, get_pods
from collectors.metrics import get_node_metrics, get_pod_metrics
from analyzers.capacity import analyze_capacity


print("=" * 80)
print("TESTE — CAPACITY ANALYZER")
print("=" * 80)

nodes = get_nodes()
pods = get_pods()

node_metrics = get_node_metrics()
pod_metrics = get_pod_metrics()

print()
print("Dados coletados:")
print(f"  Nodes........: {len(nodes.get('items', []))}")
print(f"  Pods.........: {len(pods.get('items', []))}")
print(f"  Node metrics.: {len(node_metrics)}")
print(f"  Pod metrics..: {len(pod_metrics)}")

print()
print("Executando análise...")

capacity = analyze_capacity(
    nodes,
    pods,
    node_metrics,
    pod_metrics,
)

print()
print(f"Pools analisados: {len(capacity)}")

for pool_name, analysis in capacity.items():

    bucket = analysis["capacity"]
    metrics = analysis["metrics"]

    print()
    print("-" * 80)
    print(f"POOL: {pool_name}")
    print("-" * 80)

    print(f"Nodes: {bucket['node_count']}")
    print(f"Pods:  {bucket['pod_count']}")

    print()
    print("CPU")
    print(
        f"  Allocatable.....: {bucket['cpu_allocatable']}m"
    )
    print(
        f"  Requests........: {bucket['cpu_requests']}m"
    )
    print(
        f"  Usage...........: {bucket['cpu_usage']}m"
    )
    print(
        f"  Req/Alloc.......: "
        f"{metrics['cpu_req_vs_alloc_pct']}%"
    )
    print(
        f"  Usage/Alloc.....: "
        f"{metrics['cpu_usage_vs_alloc_pct']}%"
    )
    print(
        f"  Usage/Request...: "
        f"{metrics['cpu_usage_vs_req_pct']}%"
    )

    print()
    print("MEMORY")

    print(
        f"  Allocatable.....: "
        f"{bucket['mem_allocatable']}"
    )

    print(
        f"  Requests........: "
        f"{bucket['mem_requests']}"
    )

    print(
        f"  Usage...........: "
        f"{bucket['mem_usage']}"
    )

    print(
        f"  Req/Alloc.......: "
        f"{metrics['mem_req_vs_alloc_pct']}%"
    )

    print(
        f"  Usage/Alloc.....: "
        f"{metrics['mem_usage_vs_alloc_pct']}%"
    )

    print(
        f"  Usage/Request...: "
        f"{metrics['mem_usage_vs_req_pct']}%"
    )

print()
print("=" * 80)
print("TESTE CONCLUÍDO")
print("=" * 80)
