from collections import Counter

from collectors.kubernetes import get_pods
from collectors.metrics import get_pod_metrics


pods = get_pods()
pod_metrics = get_pod_metrics()

items = pods.get("items", [])

missing = []

for pod in items:

    namespace = pod["metadata"]["namespace"]
    name = pod["metadata"]["name"]

    phase = pod.get("status", {}).get("phase", "-")

    if phase not in ("Running", "Pending"):
        continue

    key = f"{namespace}/{name}"

    if key not in pod_metrics:

        missing.append({
            "namespace": namespace,
            "name": name,
            "phase": phase,
        })


print("=" * 80)
print("METRICS COVERAGE DIAGNOSTIC")
print("=" * 80)

print()
print(f"Pods sem métricas: {len(missing)}")

print()
print("Por namespace")
print("-" * 80)

counter = Counter(
    item["namespace"]
    for item in missing
)

for namespace, count in counter.most_common():

    print(
        f"{namespace:<50} {count}"
    )

print()
print("=" * 80)
print("TOP 50 PODS SEM MÉTRICAS")
print("=" * 80)

for item in missing[:50]:

    print(
        f"{item['namespace']}/"
        f"{item['name']} "
        f"[{item['phase']}]"
    )

print()
print("=" * 80)
