import unittest

from analyzers.costs import apply_costs, estimate, fmt_brl

GIB = 1024 ** 3
SETTINGS = {"currency": "BRL", "cpu_month": 60.0, "gb_month": 15.0}
CAPACITY = {"w": {"capacity": {"node_count": 3, "cpu_allocatable": 6000, "mem_allocatable": 12 * GIB}}}


class CostsTest(unittest.TestCase):
    def test_pool_reduction_saves_one_node(self):
        # 1 node = 2 vCPU × 60 + 4 GB × 15 = 180
        self.assertEqual(estimate({"type": "UNDERUTILIZED_POOL", "pool": "w"}, CAPACITY, SETTINGS), 180.0)

    def test_rightsizing_uses_delta_times_replicas(self):
        rec = {"type": "RIGHTSIZE_REQUESTS", "operation": {"params": {"delta": {"cpu_m": 1500, "mem_b": 2 * GIB}}}}
        self.assertEqual(estimate(rec, CAPACITY, SETTINGS), 120.0)  # 1.5×60 + 2×15

    def test_increase_is_extra_cost_and_not_summed(self):
        recs = [{"type": "INCREASE_REQUESTS", "action": "Ajustar.", "status": "pending",
                 "operation": {"params": {"delta": {"cpu_m": -500, "mem_b": 0}}}},
                {"type": "UNDERUTILIZED_POOL", "pool": "w", "action": "Reduzir.", "status": "pending"}]
        total = apply_costs(recs, CAPACITY, SETTINGS)
        self.assertEqual(total, 180.0)
        self.assertIn("Custo adicional estimado: R$ 30,00/mês", recs[0]["action"])
        self.assertIn("Economia estimada: R$ 180,00/mês", recs[1]["action"])

    def test_without_settings_nothing_changes(self):
        recs = [{"type": "UNDERUTILIZED_POOL", "pool": "w", "action": "Reduzir."}]
        self.assertEqual(apply_costs(recs, CAPACITY, {"cpu_month": 0, "gb_month": 0}), 0)
        self.assertEqual(recs[0]["action"], "Reduzir.")
        self.assertEqual(fmt_brl(1234.5), "R$ 1.234,50")


if __name__ == "__main__":
    unittest.main()
