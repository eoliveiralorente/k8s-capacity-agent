from config import (
    CPU_USAGE_LOW_PCT,
    CPU_USAGE_HIGH_PCT,
    MEM_USAGE_HIGH_PCT,
    REQUEST_ALLOC_HIGH_PCT,
    EFFICIENCY_LOW_PCT,
)


def recommend_pool(pool_name, bucket, metrics):

    recommendations = []

    if bucket["node_count"] == 0:
        return recommendations

    # --------------------------------------------------------
    # CPU SUBUTILIZADA
    # --------------------------------------------------------

    if (
        metrics["cpu_usage_vs_alloc_pct"]
        < CPU_USAGE_LOW_PCT
        and metrics["cpu_req_vs_alloc_pct"]
        < 50
        and bucket["node_count"] > 1
    ):

        recommendations.append({
            "type": "UNDERUTILIZED_POOL",
            "severity": "LOW",
            "pool": pool_name,
            "message": (
                f"CPU subutilizada "
                f"({metrics['cpu_usage_vs_alloc_pct']}% "
                "do allocatable)."
            ),
            "action": (
                "Avaliar redução do número de nodes "
                "ou utilização de máquinas menores."
            ),
        })

    # --------------------------------------------------------
    # MEMÓRIA
    # --------------------------------------------------------

    if (
        metrics["mem_usage_vs_alloc_pct"]
        > MEM_USAGE_HIGH_PCT
        or
        metrics["mem_req_vs_alloc_pct"]
        > REQUEST_ALLOC_HIGH_PCT
    ):

        recommendations.append({
            "type": "MEMORY_PRESSURE",
            "severity": "HIGH",
            "pool": pool_name,
            "message": (
                f"Pressão de memória detectada. "
                f"Usage={metrics['mem_usage_vs_alloc_pct']}%, "
                f"Requests={metrics['mem_req_vs_alloc_pct']}%."
            ),
            "action": (
                "Avaliar aumento de capacidade "
                "ou revisão dos requests."
            ),
        })

    # --------------------------------------------------------
    # CPU SUPERPROVISIONADA
    # --------------------------------------------------------

    if (
        metrics["cpu_req_vs_alloc_pct"]
        > REQUEST_ALLOC_HIGH_PCT
        and
        metrics["cpu_usage_vs_req_pct"]
        < EFFICIENCY_LOW_PCT
    ):

        recommendations.append({
            "type": "CPU_OVERPROVISIONED",
            "severity": "MEDIUM",
            "pool": pool_name,
            "message": (
                f"CPU superprovisionada. "
                f"Requests={metrics['cpu_req_vs_alloc_pct']}%, "
                f"Usage/Request={metrics['cpu_usage_vs_req_pct']}%."
            ),
            "action": (
                "Revisar CPU requests antes "
                "de redimensionar o pool."
            ),
        })

    # --------------------------------------------------------
    # CPU ALTA
    # --------------------------------------------------------

    if (
        metrics["cpu_usage_vs_alloc_pct"]
        > CPU_USAGE_HIGH_PCT
    ):

        recommendations.append({
            "type": "CPU_PRESSURE",
            "severity": "HIGH",
            "pool": pool_name,
            "message": (
                f"CPU elevada "
                f"({metrics['cpu_usage_vs_alloc_pct']}%)."
            ),
            "action": (
                "Avaliar expansão do pool "
                "ou redistribuição dos workloads."
            ),
        })

    return recommendations