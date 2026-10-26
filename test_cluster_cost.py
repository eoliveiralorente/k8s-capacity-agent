import unittest

from analyzers.cluster_cost import build_cost_inputs, compute_cluster_cost, price_node
from analyzers.costs import apply_costs

GI = 1024 ** 3


def node(name, pool, machine, cpu, mem_gi):
    return {"metadata": {"name": name, "labels": {"node-pool": pool, "node.kubernetes.io/instance-type": machine}},
            "status": {"allocatable": {"cpu": str(cpu), "memory": f"{mem_gi}Gi"},
                       "capacity": {"cpu": str(cpu), "memory": f"{mem_gi}Gi"}}}


def pod(ns, node_name, cpu_m, mem_mi, phase="Running"):
    return {"metadata": {"namespace": ns}, "status": {"phase": phase},
            "spec": {"nodeName": node_name,
                     "containers": [{"resources": {"requests": {"cpu": f"{cpu_m}m", "memory": f"{mem_mi}Mi"}}}]}}


NODES = {"items": [node("a1", "general", "std-8x32", 8, 32), node("a2", "general", "std-8x32", 8, 32),
                   node("m1", "memory", "mem-8x64", 8, 64)]}
PODS = {"items": [pod("loja", "a1", 4000, 16384), pod("loja", "a2", 2000, 8192),
                  pod("dados", "m1", 1000, 32768), pod("velho", "a1", 1000, 1024, phase="Succeeded")]}
SETTINGS = {"cpu_month": 0, "gb_month": 0,
            "machine_prices": [{"match": "std-8x32", "price": 1.0, "unit": "hour"},
                               {"match": "memory", "price": 1000, "unit": "month"}],
            "fixed_costs": [{"name": "Load balancer", "monthly": 60, "qty": 2}]}


class ClusterCostTest(unittest.TestCase):
    def setUp(self):
        self.cost = compute_cluster_cost(build_cost_inputs(NODES, PODS), SETTINGS)

    def test_prices_by_machine_and_pool(self):
        # 2 × (1,00/h × 730) + 1.000 do pool memory + 120 fixos
        self.assertEqual(self.cost["nodes_monthly"], 2460.0)
        self.assertEqual(self.cost["total_monthly"], 2580.0)
        self.assertEqual(self.cost["accuracy"], "tabela")
        self.assertEqual(self.cost["by_pool"]["general"]["per_node"], 730.0)

    def test_allocation_plus_idle_equals_nodes(self):
        c = self.cost
        self.assertAlmostEqual(c["allocated_monthly"] + c["idle_monthly"], c["nodes_monthly"], places=1)
        self.assertGreater(c["idle_monthly"], 0)
        names = [r["namespace"] for r in c["by_namespace"]]
        self.assertEqual(names[0], "loja")       # maior reserva
        self.assertNotIn("velho", names)         # pod finalizado não paga

    def test_half_node_requested_pays_half(self):
        a1 = next(n for n in self.cost["nodes"] if n["name"] == "a1")
        self.assertEqual(a1["allocated"], 365.0)  # 50% de CPU e 50% de memória

    def test_fallback_and_unpriced(self):
        n = {"name": "x", "pool": "p", "machine": "z", "cpu_cap_m": 2000, "mem_cap_b": 4 * GI}
        self.assertEqual(price_node(n, {"cpu_month": 100, "gb_month": 10}), (240.0, "aproximado"))
        self.assertEqual(price_node(n, {}), (None, None))
        self.assertEqual(price_node(n, {"machine_prices": [{"match": "*", "price": 50}]}), (50.0, "tabela"))

    def test_pool_reduction_uses_real_node_price(self):
        recs = [{"type": "UNDERUTILIZED_POOL", "pool": "general", "action": "Reduzir.", "status": "pending"}]
        self.assertEqual(apply_costs(recs, {}, SETTINGS, self.cost), 730.0)
        self.assertIn("R$ 730,00/mês", recs[0]["action"])


    def test_history_follows_autoscaling(self):
        from datetime import datetime, timedelta, timezone

        from analyzers.cluster_cost import history_cost

        now = datetime(2026, 10, 26, 12, tzinfo=timezone.utc)
        samples = []
        for h in range(48, 0, -1):  # 48 h: general com 2 nodes, metade do tempo com 4
            ts = (now - timedelta(hours=h)).isoformat()
            samples.append({"timestamp": ts, "pool": "general", "node_count": 4 if h % 2 else 2})
            samples.append({"timestamp": ts, "pool": "memory", "node_count": 1})
        hist = history_cost(self.cost, samples, now=now)
        self.assertTrue(hist["available"] and hist["autoscaling"])
        self.assertEqual(hist["pools"]["general"]["avg_nodes"], 3.0)
        # 3 × 730 + 1 × 1000 + 120 fixos
        self.assertEqual(hist["monthly"], 3310.0)
        self.assertEqual(hist["spend_window_days"], 2.0)

    def test_history_needs_24h(self):
        from datetime import datetime, timedelta, timezone

        from analyzers.cluster_cost import history_cost

        now = datetime(2026, 10, 26, 12, tzinfo=timezone.utc)
        samples = [{"timestamp": (now - timedelta(hours=h)).isoformat(), "pool": "general", "node_count": 2}
                   for h in range(5, 0, -1)]
        self.assertFalse(history_cost(self.cost, samples, now=now)["available"])


if __name__ == "__main__":
    unittest.main()
