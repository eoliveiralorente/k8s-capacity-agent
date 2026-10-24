import unittest

from analyzers.score import build_overview


def node(name, cpu_use, cpu_req, ready=True, mem=40.0, cp=False):
    return {"name": name, "pool": "w", "ready": ready, "control_plane": cp, "cpu_alloc_m": 4000,
            "cpu_usage_pct": cpu_use, "cpu_req_pct": cpu_req, "mem_usage_pct": mem, "mem_req_pct": 50.0}


class ScoreTest(unittest.TestCase):
    def test_healthy_cluster_with_savings(self):
        report = {
            "nodes_usage": [node("a", 40.0, 60.0), node("b", 30.0, 50.0), node("m", 50.0, 10.0, cp=True)],
            "summary": {"pods": 50, "pending_pods": 0, "cost_settings": {"cpu_month": 100, "gb_month": 20}},
            "health": {"checks": [{"type": "x", "status": "OK"}]},
            "recommendations": [
                {"id": "r1", "type": "RIGHTSIZE_REQUESTS", "pool": "ns/d/a", "action": "x", "estimated_monthly": 120.0},
                {"id": "r2", "type": "INCREASE_REPLICAS", "pool": "ns/d/b", "action": "y", "estimated_monthly": -50.0},
                {"id": "r3", "type": "REDUCE_REPLICAS", "pool": "ns/d/c", "action": "z", "estimated_monthly": 300.0},
            ],
        }
        o = build_overview(report)
        self.assertEqual(o["score"], 100)
        self.assertEqual(o["status"], "Saudável")
        self.assertIn("R$ 420", o["headline"])
        self.assertEqual([s["id"] for s in o["top_savings"]], ["r3", "r1"])
        self.assertEqual(o["kpis"]["cpu_efficiency_pct"], 64)  # control plane fora
        self.assertEqual(o["kpis"]["nodes_ready"], 3)

    def test_critical_risks_lower_score(self):
        report = {
            "nodes_usage": [node("a", 20.0, 80.0, ready=False, mem=95.0)],
            "unhealthy_pods": [{"namespace": "app", "name": "p", "status": "CrashLoopBackOff", "restarts": 9}],
            "summary": {"pods": 10, "pending_pods": 2, "cost_settings": {}},
            "health": {"checks": [{"type": "x", "status": "FAIL"}]},
            "recommendations": [],
        }
        o = build_overview(report)
        self.assertLess(o["score"], 60)
        self.assertEqual(o["status"], "Crítico")
        self.assertEqual(o["top_risks"][0]["severity"], "HIGH")
        self.assertIsNone(o["kpis"]["savings_monthly"])
        self.assertIn("crítico", o["headline"])
        self.assertEqual(o["kpis"]["pods_ok_pct"], 70.0)


if __name__ == "__main__":
    unittest.main()
