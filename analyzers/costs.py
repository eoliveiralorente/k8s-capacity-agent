"""Estimativa de custo/economia mensal das recomendações (R$).

Modelo simples e transparente, configurável por empresa:
  custo de 1 vCPU/mês  e  custo de 1 GB de RAM/mês.
- Reduzir pool: economia = recursos de 1 node (allocatable médio do pool).
- Rightsizing: economia potencial = (request atual − proposto) × réplicas.
  Só vira economia real quando a sobra permite remover nodes — por isso "potencial".
- Aumentar requests: valor negativo (custo adicional) — mais segurança, mais reserva.
"""
import os

GIB = 1024 ** 3


def default_settings():
    return {
        "currency": "BRL",
        "cpu_month": float(os.getenv("CAPACITY_AGENT_COST_CPU_MONTH", "0") or 0),
        "gb_month": float(os.getenv("CAPACITY_AGENT_COST_GB_MONTH", "0") or 0),
    }


def _value(cpu_m, mem_b, settings):
    return round(cpu_m / 1000 * settings["cpu_month"] + mem_b / GIB * settings["gb_month"], 2)


def estimate(rec, capacity, settings):
    if not settings or (not settings.get("cpu_month") and not settings.get("gb_month")):
        return None
    rec_type = rec.get("type")
    if rec_type == "UNDERUTILIZED_POOL":
        bucket = (capacity.get(rec.get("pool")) or {}).get("capacity", {})
        nodes = bucket.get("node_count") or 0
        if not nodes:
            return None
        return _value(bucket.get("cpu_allocatable", 0) / nodes, bucket.get("mem_allocatable", 0) / nodes, settings)
    delta = (rec.get("operation") or {}).get("params", {}).get("delta")
    if delta:
        return _value(delta.get("cpu_m", 0), delta.get("mem_b", 0), settings)
    return None


def fmt_brl(value):
    sign = "-" if value < 0 else ""
    text = f"{abs(value):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{sign}R$ {text}"


def apply_costs(recommendations, capacity, settings):
    total = 0.0
    for rec in recommendations:
        value = estimate(rec, capacity, settings)
        rec["estimated_monthly"] = value
        if value is None:
            continue
        if value >= 0:
            label = "Economia estimada" if rec.get("type") == "UNDERUTILIZED_POOL" else "Economia potencial"
            rec["action"] = f"{rec.get('action', '')} {label}: {fmt_brl(value)}/mês."
            if rec.get("status", "pending") in ("pending", "approved"):
                total += value
        else:
            rec["action"] = f"{rec.get('action', '')} Custo adicional estimado: {fmt_brl(-value)}/mês (mais segurança)."
    return round(total, 2)
