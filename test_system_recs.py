"""1.3.2: componentes gerenciados pelo provedor e requests em sentidos opostos."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from alerts.rules import build_alerts
from analyzers.score import build_overview
from analyzers.workloads import collect_workloads, rightsizing_recommendations
from engine.recommendations import enrich_recommendations, is_system_rec
from test_workloads import _pod, _series


def _rec(ns, severity="HIGH", monthly=0.0, rtype="INCREASE_REQUESTS"):
    return {"type": rtype, "severity": severity, "pool": f"{ns}/DaemonSet/npd/npd", "source": "workload",
            "action": "Ajustar requests.", "confidence": "media", "estimated_monthly": monthly,
            "operation": {"kind": "manual_review", "executable": False, "params": {"namespace": ns}}}


class SystemRecsTest(unittest.TestCase):
    def test_enrich_marks_system_and_lowers_severity(self):
        items = enrich_recommendations([_rec("kube-system"), _rec("app")], [])
        sys_item = next(i for i in items if i["pool"].startswith("kube-system"))
        app_item = next(i for i in items if i["pool"].startswith("app"))
        self.assertTrue(sys_item["system"])
        self.assertEqual(sys_item["severity"], "LOW")
        self.assertFalse(app_item["system"])
        self.assertEqual(app_item["severity"], "HIGH")
        self.assertTrue(is_system_rec(_rec("kube-system")))
        self.assertFalse(is_system_rec(_rec("monitoring")))  # protegido, mas é do cliente

    def test_system_rec_no_alert_no_savings(self):
        recs = enrich_recommendations([_rec("kube-system", monthly=27.0), _rec("app", monthly=10.0)], [])
        for r in recs:
            r["severity"] = "HIGH"  # mesmo se viesse HIGH, componente do sistema não alerta
            r["estimated_monthly"] = 27.0 if r["system"] else 10.0
        app = next(r for r in recs if not r["system"])
        report = {"nodes_usage": [], "summary": {"pods": 1, "cost_settings": {"cpu_month": 1}},
                  "health": {"checks": []}, "recommendations": recs, "decision": {"reasons": []}}
        keys = [a["key"] for a in build_alerts(report)]
        self.assertEqual(keys, [f"rec:{app['id']}"])
        self.assertEqual(build_overview(report)["kpis"]["savings_monthly"], 10.0)

    def test_gate_counts_skip_system(self):
        from approval import gate, store
        with tempfile.TemporaryDirectory() as tmp, patch.object(store, "STATE_DIR", tmp), \
                patch.object(gate, "load_recommendations", return_value={"items": [
                    {"status": "pending", "system": True}, {"status": "pending"}, {"status": "rejected"}]}):
            counts = gate.gate_summary()["counts"]
        self.assertEqual(counts["pending"], 1)
        self.assertEqual(counts["system_pending"], 1)

    def test_directions_for_mixed_requests(self):
        # CPU muito acima do uso (desce) e memória perto do pico (sobe)
        _, specs = collect_workloads({"items": [_pod(cpu="1000m", mem="128Mi")]}, {})
        recs = rightsizing_recommendations(specs, {"app/Deployment/web/web": _series(20, 20, 125)})
        self.assertEqual(recs[0]["directions"], {"cpu": "down", "memory": "up"})
        self.assertNotIn("CPU 1000m → 1000m", recs[0]["action"])


if __name__ == "__main__":
    unittest.main()
