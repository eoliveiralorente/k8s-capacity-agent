"""Recomendações de réplicas e HPA (Deployments e StatefulSets).

Usa o histórico por container (p95 de CPU, pico de memória) e o estado atual
dos controladores e HPAs. Workloads gerenciados por GitOps (ArgoCD/Flux) viram
recomendação manual: alterar via kubectl seria revertido pelo controlador.
"""
import math
import re

from analyzers.workloads import PROTECTED_NAMESPACES, _confidence, _percentile, samples_text

MIN_HA_REPLICAS = 2
TARGET_UTIL = 0.6          # ocupação alvo do request após o ajuste
LOW_UTIL = 0.3             # abaixo disso: sobra
HIGH_UTIL = 0.8            # acima disso: pressão
LOW_MEM_UTIL = 0.5
BURST_RATIO = 2.0          # pico/mediana para considerar carga variável
HPA_CPU_TARGET = 70
SCALABLE_KINDS = {"Deployment", "StatefulSet"}

GITOPS_LABELS = ("argocd.argoproj.io/instance", "kustomize.toolkit.fluxcd.io/name", "helm.toolkit.fluxcd.io/name")
GITOPS_ANNOTATIONS = ("argocd.argoproj.io/tracking-id",)


def gitops_managed(metadata):
    labels = metadata.get("labels") or {}
    annotations = metadata.get("annotations") or {}
    return any(l in labels for l in GITOPS_LABELS) or any(a in annotations for a in GITOPS_ANNOTATIONS)


def _index_controllers(controllers):
    index = {}
    for item in (controllers or {}).get("items", []):
        kind = item.get("kind")
        meta = item.get("metadata", {})
        if kind in SCALABLE_KINDS:
            index[(meta.get("namespace"), kind, meta.get("name"))] = item
    return index


def _index_hpas(hpas):
    index = {}
    for item in (hpas or {}).get("items", []):
        ref = item.get("spec", {}).get("scaleTargetRef", {})
        ns = item.get("metadata", {}).get("namespace")
        index[(ns, ref.get("kind"), ref.get("name"))] = item
    return index


def _aggregate(specs, history):
    """Por workload: soma de requests, p95/mediana de CPU e pico de memória (por réplica)."""
    workloads = {}
    for key, spec in specs.items():
        if spec["kind"] not in SCALABLE_KINDS:
            continue
        wkey = (spec["namespace"], spec["kind"], spec["name"])
        w = workloads.setdefault(wkey, {"cpu_req": 0, "mem_req": 0, "cpu_p95": 0, "cpu_p50": 0,
                                        "mem_max": 0, "series_len": [], "series": None,
                                        "cpu_req_missing": False, "observed": spec.get("replicas", 1)})
        series = history.get(key) or []
        w["cpu_req"] += spec["cpu_req_m"]
        w["mem_req"] += spec["mem_req_b"]
        w["cpu_req_missing"] = w["cpu_req_missing"] or not spec["cpu_req_m"]
        if series:
            w["cpu_p95"] += _percentile([s[1] for s in series], 95)
            w["cpu_p50"] += _percentile([s[1] for s in series], 50)
            w["mem_max"] += max(s[2] for s in series)
            w["series_len"].append(len(series))
            if w["series"] is None or len(series) < len(w["series"]):
                w["series"] = series  # usa a menor série para a confiança (conservador)
    return workloads


def _rec(rec_type, severity, ns, kind, name, action, confidence, operation):
    return {"type": rec_type, "severity": severity, "pool": f"{ns}/{kind}/{name}", "source": "scaling",
            "action": action, "message": action, "confidence": confidence, "operation": operation}


def _manual(params, reason):
    return {"kind": "manual_review", "executable": False, "params": {**params, "reason": reason},
            "dry_run_command": None, "execute_command": None}


def scaling_recommendations(specs, history, controllers, hpas):
    controller_index = _index_controllers(controllers)
    hpa_index = _index_hpas(hpas)
    recs = []

    for (ns, kind, name), w in _aggregate(specs, history).items():
        controller = controller_index.get((ns, kind, name))
        if not controller or not w["series"]:
            continue
        meta = controller.get("metadata", {})
        replicas = controller.get("spec", {}).get("replicas", 1) or 0
        hpa = hpa_index.get((ns, kind, name))
        confidence, hours = _confidence(w["series"])
        period = f"{hours / 24:.1f} dias" if hours >= 24 else f"{hours:.0f} h"
        base = f"Base: {samples_text(len(w['series']))} em {period}, confiança {confidence}."
        cpu_util = (w["cpu_p95"] / w["cpu_req"]) if w["cpu_req"] else None
        mem_util = (w["mem_max"] / w["mem_req"]) if w["mem_req"] else None
        params = {"namespace": ns, "kind": kind, "name": name}

        blockers = []
        if ns in PROTECTED_NAMESPACES:
            blockers.append(f"namespace protegido ({ns})")
        if confidence == "baixa":
            blockers.append("histórico insuficiente (confiança baixa)")
        if gitops_managed(meta):
            blockers.append("workload gerenciado por GitOps — altere no repositório (o ArgoCD/Flux reverteria o kubectl)")

        def op(kind_name, extra):
            p = {**params, **extra}
            return _manual(p, "; ".join(blockers)) if blockers else {"kind": kind_name, "executable": True, "params": p}

        per_pod_cpu, per_pod_mem = w["cpu_req"], w["mem_req"]

        if hpa:
            spec = hpa.get("spec", {})
            status = hpa.get("status", {})
            hpa_name = hpa.get("metadata", {}).get("name")
            max_r, min_r = spec.get("maxReplicas", 0), spec.get("minReplicas", 1)
            current = status.get("currentReplicas", replicas)
            if w["cpu_req_missing"]:
                recs.append(_rec("HPA_WITHOUT_REQUESTS", "MEDIUM", ns, kind, name,
                                 f"O HPA {hpa_name} controla {kind.lower()}/{name}, mas há container sem request de CPU: "
                                 "o HPA por CPU não consegue calcular a utilização. Defina requests de CPU.",
                                 confidence, _manual({**params, "hpa": hpa_name}, "Defina requests de CPU primeiro")))
            elif max_r and current >= max_r and (cpu_util or 0) >= HIGH_UTIL:
                new_max = max(max_r + 1, math.ceil(max_r * 1.5))
                recs.append(_rec("HPA_AT_MAX", "HIGH", ns, kind, name,
                                 f"HPA {hpa_name} está no limite ({current}/{max_r} réplicas) com CPU p95 em "
                                 f"{round(cpu_util * 100)}% do request. Aumentar maxReplicas {max_r} → {new_max}. {base}",
                                 confidence, op("k8s_patch_hpa_max", {"hpa": hpa_name, "current_max": max_r,
                                                                      "target_max": new_max})))
            continue  # com HPA, não mexemos em replicas diretamente

        if replicas == 0:
            continue

        # Carga variável: HPA é melhor que réplicas fixas (escala no pico, economiza no vale).
        bursty = w["cpu_p50"] and w["cpu_p95"] / max(w["cpu_p50"], 1) >= BURST_RATIO
        if kind == "Deployment" and replicas >= MIN_HA_REPLICAS and not w["cpu_req_missing"] and bursty:
            peak_need = math.ceil(replicas * (cpu_util or 0) / TARGET_UTIL) + 1
            max_r = max(replicas * 2, replicas + 2, peak_need)
            recs.append(_rec("CREATE_HPA", "MEDIUM" if (cpu_util or 0) >= HIGH_UTIL else "LOW", ns, kind, name,
                             f"Carga variável em deployment/{name} (pico {round(w['cpu_p95'])}m vs mediana "
                             f"{round(w['cpu_p50'])}m). Criar HPA: min {replicas}, max {max_r}, alvo {HPA_CPU_TARGET}% CPU. {base}",
                             confidence, op("k8s_create_hpa", {"min_replicas": replicas, "max_replicas": max_r,
                                                               "cpu_percent": HPA_CPU_TARGET})))
            continue

        if cpu_util is not None and cpu_util >= HIGH_UTIL:
            new_r = max(replicas + 1, math.ceil(replicas * cpu_util / TARGET_UTIL))
            recs.append(_rec("INCREASE_REPLICAS", "MEDIUM", ns, kind, name,
                             f"Aumentar réplicas de {kind.lower()}/{name}: {replicas} → {new_r} "
                             f"(CPU p95 em {round(cpu_util * 100)}% do request). {base}",
                             confidence, op("k8s_scale", {"current_replicas": replicas, "target_replicas": new_r,
                                                          "delta": {"cpu_m": -(new_r - replicas) * per_pod_cpu,
                                                                    "mem_b": -(new_r - replicas) * per_pod_mem}})))
            continue

        if (replicas > MIN_HA_REPLICAS and cpu_util is not None and cpu_util < LOW_UTIL
                and (mem_util is None or mem_util < LOW_MEM_UTIL)):
            new_r = max(MIN_HA_REPLICAS, math.ceil(replicas * cpu_util / TARGET_UTIL))
            if new_r < replicas:
                recs.append(_rec("REDUCE_REPLICAS", "LOW", ns, kind, name,
                                 f"Reduzir réplicas de {kind.lower()}/{name}: {replicas} → {new_r} "
                                 f"(CPU p95 em {round(cpu_util * 100)}% do request; mínimo de {MIN_HA_REPLICAS} "
                                 f"para alta disponibilidade). {base}",
                                 confidence, op("k8s_scale", {"current_replicas": replicas, "target_replicas": new_r,
                                                              "delta": {"cpu_m": (replicas - new_r) * per_pod_cpu,
                                                                        "mem_b": (replicas - new_r) * per_pod_mem}})))
                continue

    return recs


NAME_RE = re.compile(r"[a-z0-9](?:[-a-z0-9.]*[a-z0-9])?")
