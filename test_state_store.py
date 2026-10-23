import json
import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from accounts import store as account_store
from approval import gate
from approval import store
from tenant_context import current_cluster_id, current_tenant_id


def _rec(rec_id, executable=True):
    return {"id": rec_id, "type": "CPU_PRESSURE", "status": "pending", "severity": "HIGH",
            "operation": {"executable": executable, "params": {"target_nodes": 3}}}


class StateStoreTest(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_patch = patch.object(account_store, "DB_PATH", Path(self.tmp.name) / "a.sqlite3")
        self.dir_patch = patch.object(store, "STATE_DIR", self.tmp.name)
        self.db_patch.start()
        self.dir_patch.start()
        self.tokens = [current_tenant_id.set("t1"), current_cluster_id.set("c1")]

    def tearDown(self):
        current_cluster_id.reset(self.tokens[1])
        current_tenant_id.reset(self.tokens[0])
        self.dir_patch.stop()
        self.db_patch.stop()
        self.tmp.cleanup()

    def test_save_load_and_approve(self):
        store.save_recommendations("ev1", [_rec("a"), _rec("b", executable=False)])
        data = store.load_recommendations()
        self.assertEqual(data["evaluation_id"], "ev1")
        self.assertEqual([i["id"] for i in data["items"]], ["a", "b"])
        self.assertTrue(gate.approve("a", "Ana (ana@x.com)")["success"])
        self.assertFalse(gate.approve("a", "Ana")["success"])  # já aprovada
        self.assertFalse(gate.approve("b", "Ana")["success"])  # manual
        self.assertEqual(store.load_recommendations()["items"][0]["status"], "approved")

    def test_concurrent_approvals_only_one_wins(self):
        store.save_recommendations("ev1", [_rec("a")])
        results = []

        def worker():
            tokens = [current_tenant_id.set("t1"), current_cluster_id.set("c1")]
            results.append(gate.approve("a", "x")["success"])

        threads = [threading.Thread(target=worker) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(results.count(True), 1)

    def test_audit_unified_per_tenant(self):
        store.append_audit("evaluate", {"n": 1})
        current_cluster_id.set("c2")
        store.append_audit("evaluate", {"n": 2})
        entries = store.load_audit()
        self.assertEqual({e["cluster_id"] for e in entries}, {"c1", "c2"})
        current_tenant_id.set("t2")
        self.assertEqual(store.load_audit(), [])

    def test_legacy_files_imported_once(self):
        legacy_dir = os.path.join(self.tmp.name, "tenants", "t1", "c9")
        os.makedirs(legacy_dir)
        with open(os.path.join(legacy_dir, "recommendations.json"), "w") as handle:
            json.dump({"evaluation_id": "old", "items": [_rec("z")]}, handle)
        with open(os.path.join(legacy_dir, "audit.log"), "w") as handle:
            handle.write(json.dumps({"timestamp": "2026-01-01T00:00:00+00:00",
                                     "event": "evaluate", "details": {}}) + "\n")
        current_cluster_id.set("c9")
        self.assertEqual(store.load_recommendations()["items"][0]["id"], "z")
        self.assertEqual(len(store.load_audit()), 1)
        store.load_recommendations()
        self.assertEqual(len(store.load_audit()), 1)  # não reimporta

    def test_report_path_traversal_blocked(self):
        with self.assertRaises(FileNotFoundError):
            store.load_report("../../etc/passwd")


if __name__ == "__main__":
    unittest.main()
