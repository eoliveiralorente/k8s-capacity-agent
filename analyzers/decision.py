from config import (
    MIN_NODE_METRICS_COVERAGE,
    MIN_POD_METRICS_COVERAGE,
)


UNSAFE_SCHEDULING_CAUSES = {
    "MISSING_CONFIGMAP",
    "MISSING_SECRET",
    "IMAGE_PULL",
    "REGISTRY_AUTH",
    "REGISTRY_NOT_FOUND",
    "VOLUME_OR_PVC",
    "CONTAINER_RUNTIME",
    "UNKNOWN",
}


def evaluate_decision(
    health,
    recommendations,
    scheduling_findings,
):

    reasons = []

    allowed = True

    if not health["decision_allowed"]:
        allowed = False
        reasons.append(
            "Cluster health não permite decisão automática."
        )

    if health["node_coverage"] < MIN_NODE_METRICS_COVERAGE:
        allowed = False
        reasons.append(
            f"Cobertura de métricas dos nodes abaixo de "
            f"{MIN_NODE_METRICS_COVERAGE}%."
        )

    if health["pod_coverage"] < MIN_POD_METRICS_COVERAGE:
        allowed = False
        reasons.append(
            f"Cobertura de métricas dos pods abaixo de "
            f"{MIN_POD_METRICS_COVERAGE}%."
        )

    for item in scheduling_findings:
        cause = item.get("cause")

        if cause in UNSAFE_SCHEDULING_CAUSES:
            allowed = False
            reasons.append(
                f"Problema de scheduling não resolvível por scale: {cause}"
            )

    high_severity = [
        r for r in recommendations
        if r.get("severity") == "HIGH"
        and r.get("operation", {}).get("executable")
    ]

    if high_severity:
        reasons.append(
            f"{len(high_severity)} recomendação(ões) HIGH aguardando "
            "análise e aprovação DevOps."
        )

    return {
        "allowed": allowed,
        "reasons": reasons,
        "high_severity_count": len(high_severity),
        "executable_recommendations": len([
            r for r in recommendations
            if r.get("operation", {}).get("executable")
        ]),
    }
