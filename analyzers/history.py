"""Resumo do histórico de amostras por pool (p95, pico, confiança)."""
from datetime import datetime

MIN_SAMPLES_MEDIUM = 12      # ~3h com amostra a cada 15 min
MIN_SAMPLES_HIGH = 96        # ~1 dia
MIN_HOURS_HIGH = 72          # 3 dias cobertos


def _percentile(values, pct):
    values = sorted(v for v in values if v is not None)
    if not values:
        return None
    index = max(0, min(len(values) - 1, round(pct / 100 * (len(values) - 1))))
    return round(values[index], 1)


def _hours_between(first, last):
    try:
        return (datetime.fromisoformat(last) - datetime.fromisoformat(first)).total_seconds() / 3600
    except (TypeError, ValueError):
        return 0


def summarize_history(samples):
    by_pool = {}
    for sample in samples:
        by_pool.setdefault(sample["pool"], []).append(sample)

    result = {}
    for pool, items in by_pool.items():
        hours = _hours_between(items[0]["timestamp"], items[-1]["timestamp"])
        count = len(items)
        if count >= MIN_SAMPLES_HIGH and hours >= MIN_HOURS_HIGH:
            confidence = "alta"
        elif count >= MIN_SAMPLES_MEDIUM:
            confidence = "media"
        else:
            confidence = "baixa"
        result[pool] = {
            "samples": count,
            "hours": round(hours, 1),
            "first": items[0]["timestamp"],
            "last": items[-1]["timestamp"],
            "confidence": confidence,
            "cpu_usage_p95": _percentile([i["cpu_usage_pct"] for i in items], 95),
            "cpu_usage_max": _percentile([i["cpu_usage_pct"] for i in items], 100),
            "mem_usage_p95": _percentile([i["mem_usage_pct"] for i in items], 95),
            "mem_usage_max": _percentile([i["mem_usage_pct"] for i in items], 100),
            "cpu_req_max": _percentile([i["cpu_req_pct"] for i in items], 100),
            "mem_req_max": _percentile([i["mem_req_pct"] for i in items], 100),
        }
    return result


def describe(history):
    if not history:
        return "sem histórico"
    days = history["hours"] / 24
    period = f"{days:.1f} dias" if days >= 1 else f"{history['hours']:.0f} h"
    return (
        f"histórico: {history['samples']} amostras em {period}, "
        f"pico CPU {history['cpu_usage_max']}% / p95 {history['cpu_usage_p95']}%, "
        f"pico memória {history['mem_usage_max']}% / p95 {history['mem_usage_p95']}% "
        f"— confiança {history['confidence']}"
    )
