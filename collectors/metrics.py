from collectors.kubernetes import run


def parse_cpu(value):
    if not value:
        return 0

    value = str(value).strip()

    if value.endswith("m"):
        return int(value[:-1])

    return int(float(value) * 1000)


def parse_memory(value):
    if not value:
        return 0

    value = str(value).strip()

    units = {
        "Ki": 1024,
        "Mi": 1024 ** 2,
        "Gi": 1024 ** 3,
        "Ti": 1024 ** 4,
        "K": 1000,
        "M": 1000 ** 2,
        "G": 1000 ** 3,
        "T": 1000 ** 4,
    }

    for suffix, multiplier in units.items():
        if value.endswith(suffix):
            return int(
                float(value[:-len(suffix)]) * multiplier
            )

    return int(value)


def get_node_metrics():
    output = run("kubectl top nodes --no-headers")

    result = {}

    for line in output.splitlines():

        cols = line.split()

        if len(cols) < 5:
            continue

        result[cols[0]] = {
            "cpu": cols[1],
            "cpu_pct": cols[2],
            "mem": cols[3],
            "mem_pct": cols[4],
        }

    return result


def get_pod_metrics():
    output = run("kubectl top pods -A --no-headers")

    result = {}

    for line in output.splitlines():

        cols = line.split()

        if len(cols) < 4:
            continue

        namespace = cols[0]
        name = cols[1]

        result[f"{namespace}/{name}"] = {
            "cpu_m": parse_cpu(cols[2]),
            "mem_b": parse_memory(cols[3]),
        }

    return result


def get_container_metrics():
    """Uso atual por container: {(namespace, pod, container): {cpu_m, mem_b}}."""
    output = run("kubectl top pods -A --containers --no-headers")

    result = {}

    for line in output.splitlines():
        cols = line.split()
        if len(cols) < 5:
            continue
        try:
            result[(cols[0], cols[1], cols[2])] = {
                "cpu_m": parse_cpu(cols[3]),
                "mem_b": parse_memory(cols[4]),
            }
        except ValueError:
            continue

    return result
