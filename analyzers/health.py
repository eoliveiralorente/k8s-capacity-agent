from config import (
    MIN_NODE_METRICS_COVERAGE,
    MIN_POD_METRICS_COVERAGE,
)


def evaluate_health(
    node_count,
    running_pending_pods,
    node_metrics_count,
    pod_metrics_count,
):

    node_coverage = (
        node_metrics_count / node_count * 100
        if node_count else 0
    )

    pod_coverage = (
        pod_metrics_count / running_pending_pods * 100
        if running_pending_pods else 0
    )

    checks = []

    node_ok = node_coverage >= MIN_NODE_METRICS_COVERAGE

    pod_ok = pod_coverage >= MIN_POD_METRICS_COVERAGE

    checks.append({
        "type": "NODE_METRICS",
        "status": "OK" if node_ok else "WARNING",
        "coverage": round(node_coverage, 1),
    })

    checks.append({
        "type": "POD_METRICS",
        "status": "OK" if pod_ok else "WARNING",
        "coverage": round(pod_coverage, 1),
    })

    decision_allowed = node_ok and pod_ok

    return {
        "node_coverage": round(node_coverage, 1),
        "pod_coverage": round(pod_coverage, 1),
        "decision_allowed": decision_allowed,
        "checks": checks,
    }