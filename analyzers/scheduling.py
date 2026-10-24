#!/usr/bin/env python3

from collections import Counter, defaultdict
import re


# ============================================================
# CONSTANTES
# ============================================================

SEVERITY = {
    "INSUFFICIENT_CPU": "HIGH",
    "INSUFFICIENT_MEMORY": "HIGH",
    "UNTOLERATED_TAINT": "HIGH",
    "VOLUME_OR_PVC": "HIGH",
    "MISSING_CONFIGMAP": "HIGH",
    "MISSING_SECRET": "HIGH",
    "NODE_AFFINITY": "HIGH",
    "IMAGE_PULL": "HIGH",
    "REGISTRY_AUTH": "HIGH",
    "REGISTRY_NOT_FOUND": "HIGH",
    "AUTOSCALER": "HIGH",
    "CONTAINER_RUNTIME": "HIGH",
    "EVICTION": "HIGH",
    "POD_DISRUPTION": "MEDIUM",
    "UNKNOWN": "MEDIUM",
}


# ============================================================
# HELPERS
# ============================================================

def safe_string(value):
    if value is None:
        return ""

    return str(value).strip()


def event_message(event):
    if isinstance(event, dict):
        return safe_string(
            event.get("message", "")
        )

    if isinstance(event, str):
        return event.strip()

    return ""


def event_reason(event):
    if isinstance(event, dict):
        return safe_string(
            event.get("reason", "")
        )

    return ""


def event_namespace(event):
    if isinstance(event, dict):

        metadata = event.get(
            "metadata",
            {}
        )

        if isinstance(metadata, dict):
            return safe_string(
                metadata.get(
                    "namespace",
                    ""
                )
            )

    return ""


def event_involved_object(event):

    if isinstance(event, dict):

        obj = event.get(
            "involvedObject",
            {}
        )

        if isinstance(obj, dict):
            return obj

    return {}


def event_pod_name(event):

    obj = event_involved_object(
        event
    )

    kind = safe_string(
        obj.get(
            "kind",
            ""
        )
    )

    if kind != "Pod":
        return ""

    return safe_string(
        obj.get(
            "name",
            ""
        )
    )


# ============================================================
# CLASSIFICAÇÃO
# ============================================================

def classify_event(event):

    message = event_message(event)

    reason = event_reason(event)

    text = safe_string(
        message
    ).lower()

    reason_text = safe_string(
        reason
    ).lower()

    # ========================================================
    # 1. CONFIGMAP
    # ========================================================

    if (
        "configmap" in text
        and (
            "not found" in text
            or "does not exist" in text
            or "notfound" in text
        )
    ):
        return (
            "MISSING_CONFIGMAP",
            message
        )

    # ========================================================
    # 2. SECRET
    # ========================================================

    if (
        "secret" in text
        and (
            "not found" in text
            or "does not exist" in text
            or "notfound" in text
        )
    ):
        return (
            "MISSING_SECRET",
            message
        )

    # ========================================================
    # 3. PVC / STORAGE
    # ========================================================

    if any(
        term in text
        for term in (
            "persistentvolumeclaim",
            "persistentvolume",
            "storageclass",
            "mountvolume",
            "failedattachvolume",
            "failedmount",
            "persistent volume claim",
        )
    ):
        return (
            "VOLUME_OR_PVC",
            message
        )

    # ========================================================
    # 4. REGISTRY AUTHENTICATION
    # ========================================================

    registry_auth_patterns = (
        "403 forbidden",
        "401 unauthorized",
        "failed to authorize",
        "failed to fetch oauth token",
        "unauthorized",
        "denied: requested access",
        "pull access denied",
        "authentication required",
        "permission denied",
    )

    if any(
        term in text
        for term in registry_auth_patterns
    ):

        if (
            "artifact registry" in text
            or "docker.pkg.dev" in text
            or "oauth token" in text
            or "registry" in text
            or "image" in text
        ):
            return (
                "REGISTRY_AUTH",
                message
            )

    # ========================================================
    # 5. REGISTRY IMAGE / TAG NOT FOUND
    # ========================================================

    registry_not_found_patterns = (
        "manifest unknown",
        "name unknown",
        "repository does not exist",
        "repository not found",
        "image not found",
        "tag not found",
        "not found",
    )

    if any(
        term in text
        for term in registry_not_found_patterns
    ):

        if (
            "image" in text
            or "manifest" in text
            or "repository" in text
            or "registry" in text
            or "docker.pkg.dev" in text
        ):
            return (
                "REGISTRY_NOT_FOUND",
                message
            )

    # ========================================================
    # 6. IMAGE PULL
    # ========================================================

    if reason_text in (
        "imagepullbackoff",
        "errimagepull",
        "invalidimagename",
        "imageinspecterror",
    ):
        return (
            "IMAGE_PULL",
            message
        )

    if any(
        term in text
        for term in (
            "imagepullbackoff",
            "errimagepull",
            "pulling image",
            "failed to pull image",
            "failed to pull and unpack image",
            "failed to resolve reference",
        )
    ):
        return (
            "IMAGE_PULL",
            message
        )

    # ========================================================
    # 7. CPU
    # ========================================================

    if (
        "insufficient cpu" in text
        or "insufficient_cpu" in text
    ):
        return (
            "INSUFFICIENT_CPU",
            message
        )

    # ========================================================
    # 8. MEMORY
    # ========================================================

    if (
        "insufficient memory" in text
        or "insufficient mem" in text
    ):
        return (
            "INSUFFICIENT_MEMORY",
            message
        )

    # ========================================================
    # 9. TAINT
    # ========================================================

    if (
        "untolerated taint" in text
        or "had untolerated taint" in text
    ):
        return (
            "UNTOLERATED_TAINT",
            message
        )

    # ========================================================
    # 10. NODE AFFINITY
    # ========================================================

    if any(
        term in text
        for term in (
            "didn't match pod's node affinity",
            "didn't match pod's node selector",
            "didn't match pod affinity",
            "node(s) didn't match",
            "node affinity",
        )
    ):
        return (
            "NODE_AFFINITY",
            message
        )

    # ========================================================
    # 11. AUTOSCALER
    # ========================================================

    if any(
        term in text
        for term in (
            "didn't trigger scale-up",
            "did not trigger scale-up",
            "pod didn't trigger scale-up",
            "pod did not trigger scale-up",
            "not trigger scale-up",
            "scale-up",
            "scale up",
            "cluster autoscaler",
            "autoscaler",
        )
    ):
        return (
            "AUTOSCALER",
            message
        )

    # ========================================================
    # 12. CONTAINER RUNTIME
    # ========================================================

    if reason_text in (
        "containercreating",
        "createcontainerconfigerror",
        "runcontainererror",
        "containercannotrun",
    ):
        return (
            "CONTAINER_RUNTIME",
            message
        )

    if any(
        term in text
        for term in (
            "createcontainerconfigerror",
            "runcontainererror",
            "containercannotrun",
            "failed to create container",
            "failed to start container",
            "container runtime",
        )
    ):
        return (
            "CONTAINER_RUNTIME",
            message
        )

    # ========================================================
    # 13. EVICTION
    # ========================================================

    if reason_text in (
        "evicted",
        "nodepressure",
    ):
        return (
            "EVICTION",
            message
        )

    if any(
        term in text
        for term in (
            "pod was evicted",
            "evicted",
            "memorypressure",
            "diskpressure",
            "pidpressure",
        )
    ):
        return (
            "EVICTION",
            message
        )

    # ========================================================
    # 14. POD DISRUPTION
    # ========================================================

    if reason_text in (
        "crashloopbackoff",
        "backoff",
    ):
        return (
            "POD_DISRUPTION",
            message
        )

    if "crashloopbackoff" in text:
        return (
            "POD_DISRUPTION",
            message
        )

    # ========================================================
    # 15. UNKNOWN
    # ========================================================

    return (
        "UNKNOWN",
        message
    )


def classify_message(message):

    cause, _ = classify_event(
        {
            "message": message
        }
    )

    return cause


# ============================================================
# RESOURCE EXTRACTION
# ============================================================

def extract_resource(message):

    text = safe_string(
        message
    )

    lower = text.lower()

    resource_type = None

    # CONFIGMAP
    if "configmap" in lower:
        resource_type = "ConfigMap"

    # SECRET
    elif "secret" in lower:
        resource_type = "Secret"

    # PVC
    elif "persistentvolumeclaim" in lower:
        resource_type = "PVC"

    # STORAGE CLASS
    elif "storageclass" in lower:
        resource_type = "StorageClass"

    # PV
    elif (
        "persistentvolume" in lower
        and "persistentvolumeclaim" not in lower
    ):
        resource_type = "PV"

    # PVC GENÉRICO
    elif (
        "pvc" in lower
        and (
            "not found" in lower
            or "does not exist" in lower
        )
    ):
        resource_type = "PVC"

    if not resource_type:
        return None

    name = ""

    # ========================================================
    # EXTRAÇÃO MAIS PRECISA
    # ========================================================

    patterns = {

        "ConfigMap": [
            r'configmap\s+"([^"]+)"',
            r"configmap\s+'([^']+)'",
            r'configmap\s+([a-zA-Z0-9._-]+)',
        ],

        "Secret": [
            r'secret\s+"([^"]+)"',
            r"secret\s+'([^']+)'",
            r'secret\s+([a-zA-Z0-9._-]+)',
        ],

        "PVC": [
            r'persistentvolumeclaim\s+"([^"]+)"',
            r"persistentvolumeclaim\s+'([^']+)'",
            r'persistentvolumeclaim\s+([a-zA-Z0-9._-]+)',
            r'pvc\s+"([^"]+)"',
            r"pvc\s+'([^']+)'",
            r'pvc\s+([a-zA-Z0-9._-]+)',
        ],

        "StorageClass": [
            r'storageclass\s+"([^"]+)"',
            r"storageclass\s+'([^']+)'",
            r'storageclass\s+([a-zA-Z0-9._-]+)',
        ],

        "PV": [
            r'persistentvolume\s+"([^"]+)"',
            r"persistentvolume\s+'([^']+)'",
            r'persistentvolume\s+([a-zA-Z0-9._-]+)',
        ],
    }

    for pattern in patterns.get(
        resource_type,
        []
    ):

        match = re.search(
            pattern,
            text,
            re.IGNORECASE
        )

        if match:

            name = safe_string(
                match.group(1)
            )

            if name:
                break

    return {
        "type": resource_type,
        "name": name or "unknown",
    }


# ============================================================
# EVENT INDEX
# ============================================================

def build_event_index(events):

    index = defaultdict(list)

    if not isinstance(
        events,
        dict
    ):
        return index

    items = events.get(
        "items",
        []
    )

    if not isinstance(
        items,
        list
    ):
        return index

    for event in items:

        if not isinstance(
            event,
            dict
        ):
            continue

        pod_name = event_pod_name(
            event
        )

        namespace = event_namespace(
            event
        )

        if not pod_name:
            continue

        key = (
            f"{namespace}/"
            f"{pod_name}"
        )

        index[key].append(
            event
        )

    return index


# ============================================================
# SCHEDULING COMBINADO
# ============================================================

def get_scheduling_causes(
    pod_events
):

    causes = []

    for event in pod_events:

        cause, _ = classify_event(
            event
        )

        # Somente causas reais de scheduling
        if cause in (
            "INSUFFICIENT_CPU",
            "INSUFFICIENT_MEMORY",
            "UNTOLERATED_TAINT",
            "NODE_AFFINITY",
            "AUTOSCALER",
        ):

            if cause not in causes:
                causes.append(
                    cause
                )

    return causes


def combined_scheduling_cause(
    pod_events
):

    causes = get_scheduling_causes(
        pod_events
    )

    if len(causes) <= 1:

        if causes:
            return causes[0]

        return None

    return "SCHEDULING_COMBINED"


def combined_scheduling_action(
    causes
):

    actions = []

    if (
        "INSUFFICIENT_CPU"
        in causes
    ):
        actions.append(
            "Avaliar expansão do node pool, "
            "uso de máquinas maiores ou "
            "redução dos CPU requests."
        )

    if (
        "INSUFFICIENT_MEMORY"
        in causes
    ):
        actions.append(
            "Avaliar expansão do node pool "
            "ou aumento de memória."
        )

    if (
        "UNTOLERATED_TAINT"
        in causes
    ):
        actions.append(
            "Revisar taints dos nodes "
            "e tolerations dos Pods."
        )

    if (
        "NODE_AFFINITY"
        in causes
    ):
        actions.append(
            "Revisar nodeSelector, "
            "nodeAffinity e distribuição "
            "dos workloads."
        )

    if (
        "AUTOSCALER"
        in causes
    ):
        actions.append(
            "Investigar por que o Cluster "
            "Autoscaler não realizou scale-up. "
            "Validar node pool, min/max nodes, "
            "taints, affinity, requests e constraints."
        )

    return " ".join(actions)


# ============================================================
# POD ANALYSIS
# ============================================================

def analyze_pod(
    pod,
    pod_events
):

    findings = []

    if not isinstance(
        pod,
        dict
    ):
        return findings

    metadata = pod.get(
        "metadata",
        {}
    )

    status = pod.get(
        "status",
        {}
    )

    if not isinstance(
        metadata,
        dict
    ):
        return findings

    if not isinstance(
        status,
        dict
    ):
        return findings

    namespace = safe_string(
        metadata.get(
            "namespace",
            "default"
        )
    )

    name = safe_string(
        metadata.get(
            "name",
            ""
        )
    )

    phase = safe_string(
        status.get(
            "phase",
            ""
        )
    )

    if not name:
        return findings

    is_pending = (
        phase == "Pending"
    )

    is_failed = (
        phase == "Failed"
    )

    if not is_pending and not is_failed:
        return findings

    if not isinstance(
        pod_events,
        list
    ):
        pod_events = []

    # ========================================================
    # PRIMEIRO: PROBLEMAS DE RECURSOS
    # ========================================================

    direct_findings = []

    for event in pod_events:

        cause, message = classify_event(
            event
        )

        # Scheduling será tratado separadamente
        if cause in (
            "INSUFFICIENT_CPU",
            "INSUFFICIENT_MEMORY",
            "UNTOLERATED_TAINT",
            "NODE_AFFINITY",
            "AUTOSCALER",
        ):
            continue

        if cause == "UNKNOWN":
            continue

        if any(
            item["cause"] == cause
            for item in direct_findings
        ):
            continue

        resource = extract_resource(
            message
        )

        direct_findings.append({

            "namespace":
                namespace,

            "pod":
                name,

            "phase":
                phase,

            "cause":
                cause,

            "severity":
                SEVERITY.get(
                    cause,
                    "MEDIUM"
                ),

            "reason":
                event_reason(
                    event
                ),

            "message":
                message,

            "resource":
                resource,

            "action":
                recommendation_action(
                    cause
                ),

        })

    findings.extend(
        direct_findings
    )

    # ========================================================
    # SCHEDULING
    # ========================================================

    scheduling_causes = (
        get_scheduling_causes(
            pod_events
        )
    )

    if scheduling_causes:

        cause = combined_scheduling_cause(
            pod_events
        )

        if cause == "SCHEDULING_COMBINED":

            message = ""

            for event in pod_events:

                event_cause, event_message_value = (
                    classify_event(event)
                )

                if event_cause in scheduling_causes:

                    if event_message_value:
                        message = event_message_value
                        break

            findings.append({

                "namespace":
                    namespace,

                "pod":
                    name,

                "phase":
                    phase,

                "cause":
                    "SCHEDULING_COMBINED",

                "severity":
                    "HIGH",

                "reason":
                    "FailedScheduling",

                "message":
                    message,

                "resource":
                    None,

                "scheduling_causes":
                    scheduling_causes,

                "action":
                    combined_scheduling_action(
                        scheduling_causes
                    ),

            })

        else:

            cause = scheduling_causes[0]

            message = ""

            for event in pod_events:

                event_cause, event_message_value = (
                    classify_event(event)
                )

                if event_cause == cause:

                    message = event_message_value
                    break

            findings.append({

                "namespace":
                    namespace,

                "pod":
                    name,

                "phase":
                    phase,

                "cause":
                    cause,

                "severity":
                    SEVERITY.get(
                        cause,
                        "HIGH"
                    ),

                "reason":
                    "FailedScheduling",

                "message":
                    message,

                "resource":
                    None,

                "action":
                    recommendation_action(
                        cause
                    ),

            })

    # ========================================================
    # UNKNOWN
    # ========================================================

    if not findings:

        message = ""

        reason = ""

        if pod_events:

            message = event_message(
                pod_events[0]
            )

            reason = event_reason(
                pod_events[0]
            )

        findings.append({

            "namespace":
                namespace,

            "pod":
                name,

            "phase":
                phase,

            "cause":
                "UNKNOWN",

            "severity":
                "MEDIUM",

            "reason":
                reason,

            "message":
                message,

            "resource":
                None,

            "action":
                recommendation_action(
                    "UNKNOWN"
                ),

        })

    return findings


# ============================================================
# ACTIONS
# ============================================================

def recommendation_action(
    cause
):

    actions = {

        "INSUFFICIENT_CPU":
            (
                "Avaliar expansão do node pool, "
                "uso de máquinas maiores ou "
                "redução dos CPU requests."
            ),

        "INSUFFICIENT_MEMORY":
            (
                "Avaliar expansão do node pool "
                "ou aumento de memória."
            ),

        "UNTOLERATED_TAINT":
            (
                "Revisar taints dos nodes "
                "e tolerations dos Pods."
            ),

        "NODE_AFFINITY":
            (
                "Revisar nodeSelector, "
                "nodeAffinity e distribuição "
                "dos workloads."
            ),

        "MISSING_CONFIGMAP":
            (
                "Verificar ConfigMaps ausentes "
                "ou referências incorretas."
            ),

        "MISSING_SECRET":
            (
                "Verificar Secrets ausentes "
                "ou referências incorretas."
            ),

        "VOLUME_OR_PVC":
            (
                "Investigar PVC, PV, StorageClass "
                "e topology."
            ),

        "IMAGE_PULL":
            (
                "Verificar imagem, tag, registry, "
                "permissões de acesso e imagePullSecrets."
            ),

        "REGISTRY_AUTH":
            (
                "Validar IAM, Service Account, "
                "Workload Identity e permissões "
                "de leitura no Artifact Registry."
            ),

        "REGISTRY_NOT_FOUND":
            (
                "Validar repository, imagem e tag "
                "no Artifact Registry."
            ),

        "AUTOSCALER":
            (
                "Verificar o motivo pelo qual o "
                "Cluster Autoscaler não realizou "
                "scale-up. Validar node pool, "
                "min/max nodes, taints, affinity, "
                "requests e constraints."
            ),

        "CONTAINER_RUNTIME":
            (
                "Investigar erro de criação ou "
                "execução do container."
            ),

        "EVICTION":
            (
                "Investigar pressão de memória, "
                "CPU, disco ou PID nos nodes."
            ),

        "POD_DISRUPTION":
            (
                "Investigar restart, CrashLoopBackOff "
                "e condições do container."
            ),

        "UNKNOWN":
            (
                "Investigar eventos, condições "
                "e especificação do Pod."
            ),
    }

    return actions.get(
        cause,
        actions["UNKNOWN"]
    )


# ============================================================
# MAIN ANALYZER
# ============================================================

def analyze_scheduling(
    pods,
    events
):

    findings = []

    event_index = build_event_index(
        events
    )

    if not isinstance(
        pods,
        dict
    ):
        return findings

    items = pods.get(
        "items",
        []
    )

    if not isinstance(
        items,
        list
    ):
        return findings

    for pod in items:

        if not isinstance(
            pod,
            dict
        ):
            continue

        metadata = pod.get(
            "metadata",
            {}
        )

        if not isinstance(
            metadata,
            dict
        ):
            continue

        namespace = safe_string(
            metadata.get(
                "namespace",
                "default"
            )
        )

        name = safe_string(
            metadata.get(
                "name",
                ""
            )
        )

        if not name:
            continue

        key = (
            f"{namespace}/"
            f"{name}"
        )

        pod_events = event_index.get(
            key,
            []
        )

        pod_findings = analyze_pod(
            pod,
            pod_events
        )

        findings.extend(
            pod_findings
        )

    return findings


# ============================================================
# SUMMARIES
# ============================================================

def summarize_causes(
    findings
):

    counter = Counter()

    for item in findings:

        counter[
            item.get(
                "cause",
                "UNKNOWN"
            )
        ] += 1

    return counter


def summarize_namespaces(
    findings
):

    result = defaultdict(
        Counter
    )

    for item in findings:

        namespace = item.get(
            "namespace",
            "unknown"
        )

        cause = item.get(
            "cause",
            "UNKNOWN"
        )

        result[
            namespace
        ][
            cause
        ] += 1

    return result


def summarize_resources(
    findings
):

    counter = Counter()

    for item in findings:

        resource = item.get(
            "resource"
        )

        if not resource:
            continue

        resource_type = resource.get(
            "type",
            "UNKNOWN"
        )

        resource_name = resource.get(
            "name",
            "unknown"
        )

        counter[
            (
                resource_type,
                resource_name
            )
        ] += 1

    return counter


# ============================================================
# RECOMMENDATIONS
# ============================================================

def scheduling_recommendations(
    findings
):

    counter = Counter()

    for item in findings:

        counter[
            item.get(
                "cause",
                "UNKNOWN"
            )
        ] += 1

    mapping = {

        "INSUFFICIENT_CPU": {

            "type":
                "SCHEDULING_CPU",

            "severity":
                "HIGH",

            "action":
                (
                    "Avaliar expansão do node pool, "
                    "uso de máquinas maiores ou "
                    "redução dos CPU requests."
                ),
        },

        "INSUFFICIENT_MEMORY": {

            "type":
                "SCHEDULING_MEMORY",

            "severity":
                "HIGH",

            "action":
                (
                    "Avaliar expansão do node pool "
                    "ou aumento de memória."
                ),
        },

        "UNTOLERATED_TAINT": {

            "type":
                "TAINT_TOLERATION",

            "severity":
                "HIGH",

            "action":
                (
                    "Revisar taints dos nodes "
                    "e tolerations dos Pods."
                ),
        },

        "NODE_AFFINITY": {

            "type":
                "NODE_AFFINITY",

            "severity":
                "HIGH",

            "action":
                (
                    "Revisar nodeSelector, "
                    "nodeAffinity e distribuição "
                    "dos workloads."
                ),
        },

        "SCHEDULING_COMBINED": {

            "type":
                "SCHEDULING_COMBINED",

            "severity":
                "HIGH",

            "action":
                (
                    "Investigar múltiplas restrições "
                    "de scheduling simultaneamente: "
                    "CPU, memória, taints, affinity, "
                    "requests e Cluster Autoscaler."
                ),
        },

        "MISSING_CONFIGMAP": {

            "type":
                "MISSING_CONFIGMAP",

            "severity":
                "HIGH",

            "action":
                (
                    "Verificar ConfigMaps ausentes "
                    "ou referências incorretas."
                ),
        },

        "MISSING_SECRET": {

            "type":
                "MISSING_SECRET",

            "severity":
                "HIGH",

            "action":
                (
                    "Verificar Secrets ausentes "
                    "ou referências incorretas."
                ),
        },

        "VOLUME_OR_PVC": {

            "type":
                "PVC_SCHEDULING",

            "severity":
                "HIGH",

            "action":
                (
                    "Investigar PVC, PV, "
                    "StorageClass e topology."
                ),
        },

        "IMAGE_PULL": {

            "type":
                "IMAGE_PULL",

            "severity":
                "HIGH",

            "action":
                (
                    "Verificar imagem, tag, registry, "
                    "permissões e imagePullSecrets."
                ),
        },

        "REGISTRY_AUTH": {

            "type":
                "REGISTRY_AUTH",

            "severity":
                "HIGH",

            "action":
                (
                    "Validar IAM, Service Account, "
                    "Workload Identity e permissões "
                    "de leitura no Artifact Registry."
                ),
        },

        "REGISTRY_NOT_FOUND": {

            "type":
                "REGISTRY_NOT_FOUND",

            "severity":
                "HIGH",

            "action":
                (
                    "Validar repository, imagem "
                    "e tag no Artifact Registry."
                ),
        },

        "AUTOSCALER": {

            "type":
                "CLUSTER_AUTOSCALER",

            "severity":
                "HIGH",

            "action":
                (
                    "Investigar por que o Cluster "
                    "Autoscaler não realizou scale-up."
                ),
        },

        "CONTAINER_RUNTIME": {

            "type":
                "CONTAINER_RUNTIME",

            "severity":
                "HIGH",

            "action":
                (
                    "Investigar erro de criação "
                    "ou execução do container."
                ),
        },

        "EVICTION": {

            "type":
                "NODE_EVICTION",

            "severity":
                "HIGH",

            "action":
                (
                    "Investigar pressão de memória, "
                    "CPU, disco ou PID nos nodes."
                ),
        },

        "POD_DISRUPTION": {

            "type":
                "POD_DISRUPTION",

            "severity":
                "MEDIUM",

            "action":
                (
                    "Investigar restart, CrashLoopBackOff "
                    "e condições do container."
                ),
        },

        "UNKNOWN": {

            "type":
                "UNKNOWN_SCHEDULING",

            "severity":
                "MEDIUM",

            "action":
                (
                    "Investigar eventos, condições "
                    "e especificação do Pod."
                ),
        },
    }

    recommendations = []

    for cause, count in counter.items():

        definition = mapping.get(
            cause,
            mapping["UNKNOWN"]
        )

        recommendations.append({

            "type":
                definition["type"],

            "severity":
                definition["severity"],

            "affected_pods":
                count,

            "action":
                definition["action"],

            "requires_approval":
                True,

            "auto_execute":
                False,

        })

    return recommendations