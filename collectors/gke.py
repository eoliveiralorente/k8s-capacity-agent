import json

from config import CLUSTER, REGION, PROJECT
from collectors.kubernetes import run


def get_node_pools():

    command = (
        f"gcloud container node-pools list "
        f"--cluster {CLUSTER} "
        f"--region {REGION} "
        f"--project {PROJECT} "
        f"--format=json"
    )

    output = run(command)

    if not output:
        return []

    return json.loads(output)