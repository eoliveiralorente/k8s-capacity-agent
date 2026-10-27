import base64
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from licensing import core


def _issue(key, days=30, **extra):
    payload = {"license_id": "abc", "customer": "Cliente X", "plan": "pro", "max_clusters": 3,
               "max_users": 10, "features": ["execution", "alerts"],
               "issued_at": datetime.now(timezone.utc).isoformat(),
               "expires_at": (datetime.now(timezone.utc) + timedelta(days=days)).isoformat(), **extra}
    data = json.dumps(payload).encode()
    return json.dumps({"payload": base64.b64encode(data).decode(),
                       "signature": base64.b64encode(key.sign(data)).decode()})


class LicensingTest(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.key = Ed25519PrivateKey.generate()
        pub = Path(self.tmp.name) / "public_key.pem"
        pub.write_bytes(self.key.public_key().public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo))
        self.patches = [patch.object(core, "PUBLIC_KEY_PATH", pub),
                        patch.dict("os.environ", {"CAPACITY_AGENT_LICENSE_FILE": str(Path(self.tmp.name) / "license.json")})]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()

    def test_community_without_license(self):
        status = core.license_status()
        self.assertEqual((status["state"], status["max_clusters"], status["features"]), ("community", 1, []))
        with self.assertRaises(core.LicenseError):
            core.require_feature("execution")
        with self.assertRaises(core.LicenseError):
            core.check_limit("clusters", 1)

    def test_valid_license_unlocks_features(self):
        core.save_license_text(_issue(self.key))
        status = core.license_status()
        self.assertEqual(status["state"], "valid")
        core.require_feature("execution")
        core.check_limit("clusters", 2)
        with self.assertRaises(core.LicenseError):
            core.check_limit("clusters", 3)

    def test_tampered_or_foreign_license_rejected(self):
        text = json.loads(_issue(self.key))
        payload = json.loads(base64.b64decode(text["payload"]))
        payload["max_clusters"] = 999
        text["payload"] = base64.b64encode(json.dumps(payload).encode()).decode()
        with self.assertRaises(core.LicenseError):
            core.save_license_text(json.dumps(text))
        with self.assertRaises(core.LicenseError):
            core.save_license_text(_issue(Ed25519PrivateKey.generate()))

    def test_without_license_panel_is_locked(self):
        status = core.with_labels(core.license_status())
        self.assertTrue(status["locked"])
        self.assertEqual(status["plan_label"], "Sem licença")
        core.save_license_text(_issue(self.key))
        self.assertFalse(core.with_labels(core.license_status())["locked"])
        self.assertFalse(core.is_locked())

    def test_grace_keeps_panel_open_then_locks(self):
        core.save_license_text(_issue(self.key, days=-5))
        self.assertFalse(core.is_locked())
        core.save_license_text(_issue(self.key, days=-30))
        self.assertTrue(core.is_locked())

    def test_max_nodes_optional(self):
        core.save_license_text(_issue(self.key))
        self.assertIsNone(core.license_status()["max_nodes"])
        core.save_license_text(_issue(self.key, max_nodes=60, plan="profissional"))
        status = core.with_labels(core.license_status())
        self.assertEqual((status["max_nodes"], status["plan_label"]), (60, "Profissional"))

    def test_grace_then_community(self):
        core.save_license_text(_issue(self.key, days=-5))
        self.assertEqual(core.license_status()["state"], "grace")
        self.assertTrue(core.has_feature("execution"))
        core.save_license_text(_issue(self.key, days=-30))
        status = core.license_status()
        self.assertEqual(status["state"], "expired")
        self.assertFalse(core.has_feature("execution"))
        self.assertEqual(status["max_clusters"], 1)


class IssuePlansTest(unittest.TestCase):
    """O gerador de licença usa os limites e recursos do plano comercial."""

    def setUp(self):
        import sys

        sys.path.insert(0, str(Path(__file__).resolve().parent / "tools"))
        import license_tool

        self.tool = license_tool
        self.key = Ed25519PrivateKey.generate()
        self.patch = patch.object(license_tool, "_load_private", return_value=self.key)
        self.patch.start()

    def tearDown(self):
        self.patch.stop()

    def test_plan_defaults(self):
        _, ess = self.tool.issue_license("X", "essencial")
        self.assertEqual((ess["max_clusters"], ess["max_users"], ess["max_nodes"], ess["features"]),
                         (1, 10, 20, ["execution"]))
        _, pro = self.tool.issue_license("X", "profissional")
        self.assertEqual((pro["max_clusters"], pro["max_nodes"]), (3, 60))
        self.assertIn("ai_assistant", pro["features"])
        _, ent = self.tool.issue_license("X", "enterprise", clusters=6, users=50, nodes=150)
        self.assertEqual((ent["max_clusters"], ent["max_users"], ent["max_nodes"]), (6, 50, 150))
        self.assertEqual(set(ent["features"]), set(core.ALL_FEATURES))

    def test_nodes_zero_means_no_limit(self):
        _, payload = self.tool.issue_license("X", "essencial", nodes=0)
        self.assertNotIn("max_nodes", payload)

    def test_unknown_plan(self):
        with self.assertRaises(ValueError):
            self.tool.issue_license("X", "gold")


class NodeUsageTest(unittest.TestCase):

    def setUp(self):
        from accounts import store as account_store
        from approval import store

        self.store = store
        self.tmp = tempfile.TemporaryDirectory()
        self.patches = [patch.object(account_store, "DB_PATH", Path(self.tmp.name) / "a.sqlite3"),
                        patch.object(store, "STATE_DIR", self.tmp.name)]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()

    def _sample(self, cluster, ts, pool, nodes):
        with self.store._transaction(write=True) as c:
            c.execute("INSERT INTO metric_samples(tenant_id, cluster_id, timestamp, pool, node_count) "
                      "VALUES ('t', ?, ?, ?, ?)", (cluster, ts.isoformat(), pool, nodes))

    def test_average_over_clusters_follows_autoscaling(self):
        now = datetime(2026, 10, 27, 12, tzinfo=timezone.utc)
        for h in range(48, 0, -1):
            ts = now - timedelta(hours=h)
            self._sample("c1", ts, "general", 4 if h % 2 else 2)  # média 3
            self._sample("c1", ts, "memory", 1)
            self._sample("c2", ts, "general", 5)
        usage = self.store.installation_node_usage(now=now)
        self.assertEqual(usage["clusters"], 2)
        self.assertEqual(usage["avg_nodes"], 9.0)   # (3 + 1) + 5
        self.assertEqual(usage["peak_nodes"], 10)   # 5 + 5
        self.assertIn(usage["now_nodes"], (8, 10))


if __name__ == "__main__":
    unittest.main()
