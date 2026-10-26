import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from accounts import journal
from accounts import store as account_store
from approval import store


class DemoTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.patches = [patch.object(account_store, "DB_PATH", Path(self.tmp.name) / "a.sqlite3"),
                        patch.object(store, "STATE_DIR", self.tmp.name)]
        for p in self.patches:
            p.start()
        journal._ready = False

    def tearDown(self):
        for p in self.patches:
            p.stop()
        journal._ready = False
        self.tmp.cleanup()

    def test_seed_builds_a_full_story(self):
        from support.demo import build_snapshot, seed_demo

        snap = build_snapshot()
        self.assertTrue(snap["demo"])
        self.assertEqual(len(snap["nodes"]["items"]), 6)
        result = seed_demo(email="demo@test.local", password="x" * 12)
        self.assertTrue(result["created"])
        again = seed_demo(email="demo@test.local")
        self.assertFalse(again["created"])
        self.assertIsNone(again["password"])
        cost = again["cluster_cost"]
        self.assertEqual(cost["accuracy"], "tabela")
        self.assertGreater(cost["total_monthly"], 4000)
        self.assertGreater(cost["idle_monthly"], 0)
        self.assertTrue(cost["history"]["available"] and cost["history"]["autoscaling"])

    def test_demo_recommendations_are_executable_and_simulated(self):
        from support.demo import seed_demo
        from support.demo_exec import is_demo_cluster, simulate_operation
        from accounts.store import _connect, list_clusters
        from approval.store import load_recommendations
        from tenant_context import current_cluster_id, current_cluster_mode, current_tenant_id

        seed_demo(email="demo2@test.local", password="y" * 12)
        with _connect() as c:
            tenant = c.execute("SELECT tenant_id FROM users WHERE email='demo2@test.local'").fetchone()[0]
        cluster = list_clusters(tenant)[0]
        tokens = [(current_tenant_id, current_tenant_id.set(tenant)), (current_cluster_id, current_cluster_id.set(cluster["id"])),
                  (current_cluster_mode, current_cluster_mode.set("agent"))]
        try:
            self.assertTrue(is_demo_cluster())
            items = load_recommendations().get("items", [])
            executable = [r for r in items if (r.get("operation") or {}).get("executable")]
            self.assertGreater(len(executable), 3)
            scale = next(r for r in executable if r["operation"]["kind"] == "k8s_scale")
            out = simulate_operation(scale["operation"], dry_run=True)
            self.assertTrue(out["success"] and out["simulated"])
            self.assertIn("--dry-run=server", out["command"])
            self.assertIn("[demo]", out["output"])
            self.assertIn("kubectl scale", out["rollback_command"])
        finally:
            for var, value in reversed(tokens):
                var.reset(value)


if __name__ == "__main__":
    unittest.main()
