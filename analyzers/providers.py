"""Detecção de cloud e de node pool independente de provedor.

A análise usa apenas a API do Kubernetes; aqui só traduzimos os labels e o
spec.providerID que cada cloud coloca nos nodes.
"""
import os

# Ordem importa: o primeiro label encontrado define o pool.
POOL_LABELS = [
    "cloud.google.com/gke-nodepool",        # GKE
    "eks.amazonaws.com/nodegroup",          # EKS (managed node groups)
    "karpenter.sh/nodepool",                # Karpenter v1 (EKS e outros)
    "karpenter.sh/provisioner-name",        # Karpenter legado
    "alpha.eksctl.io/nodegroup-name",       # eksctl
    "kubernetes.azure.com/agentpool",       # AKS
    "agentpool",                            # AKS (label legado)
    "doks.digitalocean.com/node-pool",      # DigitalOcean
    "magnum.openstack.org/nodegroup",       # OpenStack Magnum (SaveInCloud)
    "node-pool",
    "nodepool",
]

# Labels extras por instalação (ex.: OKE, SaveInCloud, on-premises):
#   CAPACITY_AGENT_POOL_LABELS="meu.label/pool,outro/label"
_extra = [l.strip() for l in os.getenv("CAPACITY_AGENT_POOL_LABELS", "").split(",") if l.strip()]
POOL_LABELS = _extra + POOL_LABELS

PROVIDER_PREFIXES = {
    "gce://": "gcp",
    "aws://": "aws",
    "azure://": "azure",
    "oci://": "oci",
    "ocid1.": "oci",
    "digitalocean://": "digitalocean",
    "openstack://": "openstack",
    "vsphere://": "vsphere",
    "kind://": "kind",
}


CONTROL_PLANE_ROLES = {"master", "control-plane"}


def is_control_plane(labels):
    if labels.get("magnum.openstack.org/role") == "master":
        return True
    return any(
        f"node-role.kubernetes.io/{role}" in labels for role in CONTROL_PLANE_ROLES
    )


def node_pool(labels, fallback="worker"):
    for label in POOL_LABELS:
        value = labels.get(label)
        if value:
            return value
    return fallback


def node_provider(node):
    provider_id = (node.get("spec", {}) or {}).get("providerID", "") or ""
    for prefix, name in PROVIDER_PREFIXES.items():
        if provider_id.startswith(prefix):
            return name
    return "desconhecido" if provider_id else "sem-providerID"


def detect_cloud(nodes):
    """Retorna a cloud predominante e a contagem por provedor."""
    counts = {}
    for node in nodes.get("items", []):
        name = node_provider(node)
        counts[name] = counts.get(name, 0) + 1
    main = max(counts, key=counts.get) if counts else "desconhecido"
    return main, counts
