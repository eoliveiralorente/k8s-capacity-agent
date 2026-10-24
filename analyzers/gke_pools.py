
def merge_gke_pools(capacity, node_pools):

    for pool in node_pools:

        pool_name = pool.get("name")

        if not pool_name:
            continue

        config = pool.get("config", {})
        configured_nodes = pool.get("initialNodeCount") or 0

        gke_info = {
            "configured_nodes": configured_nodes,
            "status": pool.get("status", "UNKNOWN"),
            "version": pool.get("version", "-"),
            "machine_type": config.get("machineType", "-"),
            "management": "Gerenciado pelo usuário",
        }

        if pool_name in capacity:
            capacity[pool_name]["gke"] = gke_info
            actual = capacity[pool_name]["capacity"]["node_count"]
            capacity[pool_name]["gke"]["actual_nodes"] = actual
        else:
            capacity[pool_name] = {
                "pool": pool_name,
                "capacity": {
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
                },
                "metrics": {
                    "cpu_req_vs_alloc_pct": 0,
                    "mem_req_vs_alloc_pct": 0,
                    "cpu_usage_vs_alloc_pct": 0,
                    "mem_usage_vs_alloc_pct": 0,
                    "cpu_usage_vs_req_pct": 0,
                    "mem_usage_vs_req_pct": 0,
                },
                "gke": {
                    **gke_info,
                    "actual_nodes": 0,
                },
            }

    return capacity
