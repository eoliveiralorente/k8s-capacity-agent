import csv


def write_pool_report(path, rows):

    with open(
        path,
        "w",
        newline="",
        encoding="utf-8"
    ) as file:

        writer = csv.writer(file)

        writer.writerow([
            "Pool",
            "Nodes",
            "Pods",
            "CPU Allocatable",
            "CPU Requests",
            "CPU Usage",
            "CPU Req/Alloc %",
            "CPU Usage/Alloc %",
            "CPU Usage/Request %",
            "Memory Allocatable",
            "Memory Requests",
            "Memory Usage",
            "Memory Req/Alloc %",
            "Memory Usage/Alloc %",
            "Memory Usage/Request %",
        ])

        for row in rows:

            writer.writerow([
                row["pool"],
                row["node_count"],
                row["pod_count"],
                row["cpu_allocatable"],
                row["cpu_requests"],
                row["cpu_usage"],
                row["cpu_req_vs_alloc_pct"],
                row["cpu_usage_vs_alloc_pct"],
                row["cpu_usage_vs_req_pct"],
                row["mem_allocatable"],
                row["mem_requests"],
                row["mem_usage"],
                row["mem_req_vs_alloc_pct"],
                row["mem_usage_vs_alloc_pct"],
                row["mem_usage_vs_req_pct"],
            ])