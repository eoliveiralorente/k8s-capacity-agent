import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from accounts import store as account_store
from approval import store
from collectors import snapshot as snap
from tenant_context import current_cluster_id, current_cluster_mode, current_cluster_name, current_tenant_id

MI = 1024 ** 2


def _snapshot():
    node = {"metadata": {"name": "n1", "labels": {"magnum.openstack.org/nodegroup": "default-worker"},
                         "managedFields": [{"x": 1}]},
            "spec": {"providerID": "openstack:///n1"},
            "status": {"allocatable": {"cpu": "2", "memory": "4Gi", "pods": "110"},
                       "conditions": [{"type": "Ready", "status": "True"}], "nodeInfo": {"kubeletVersion": "v1.31"}}}
    pod = {"metadata": {"namespace": "app", "name": "web-5d9f-a", "labels": {"pod-template-hash": "5d9f"},
                        "ownerReferences": [{"kind": "ReplicaSet", "name": "web-5d9f"}],
                        "creationTimestamp": "2026-10-20T10:00:00Z"},
           "spec": {"nodeName": "n1", "containers": [{"name": "web", "resources": {"requests": {"cpu": "500m", "memory": "512Mi"}}}]},
           "status": {"phase": "Running", "containerStatuses": [{"name": "web", "ready": True, "restartCount": 0, "state": {"running": {}}}]}}
    return {"version": 1, "collected_at": "2026-10-24T10:00:00+00:00",
            "nodes": {"items": [node]}, "pods": {"items": [pod]}, "events": {"items": []},
            "node_metrics": {"n1": {"cpu": "100m", "cpu_pct": "5%", "mem": "1024Mi", "mem_pct": "25%"}},
            "pod_metrics": {"app/web-5d9f-a": {"cpu_m": 40, "mem_b": 100 * MI}},
            "container_metrics": [["app", "web-5d9f-a", "web", 40, 100 * MI]]}


class AgentModeTest(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.patches = [patch.object(account_store, "DB_PATH", Path(self.tmp.name) / "a.sqlite3"),
                        patch.object(store, "STATE_DIR", self.tmp.name)]
        for p in self.patches:
            p.start()
        self.admin = account_store.register_account("Empresa", "Admin", "a@x.com", "senha-muito-forte-1")

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()

    def test_token_lifecycle(self):
        cluster, token = account_store.create_agent_cluster(self.admin["tenant_id"], "Cliente X")
        self.assertTrue(token.startswith("cag_"))
        self.assertEqual(account_store.find_cluster_by_ingest_token(token)["id"], cluster["id"])
        self.assertIsNone(account_store.find_cluster_by_ingest_token("cag_errado"))
        self.assertIsNone(account_store.decrypt_cluster_kubeconfig(self.admin["tenant_id"], cluster["id"]))
        new_token = account_store.rotate_ingest_token(self.admin["tenant_id"], cluster["id"])
        self.assertIsNone(account_store.find_cluster_by_ingest_token(token))
        self.assertIsNotNone(account_store.find_cluster_by_ingest_token(new_token))
        self.assertEqual(account_store.list_clusters(self.admin["tenant_id"])[0]["mode"], "agent")

    def test_snapshot_roundtrip_and_validation(self):
        data = _snapshot()
        snap._slim(data["nodes"]["items"])
        self.assertNotIn("managedFields", data["nodes"]["items"][0]["metadata"])
        snap.validate_snapshot(data)
        with self.assertRaises(ValueError):
            snap.validate_snapshot({"version": 99})
        converted = snap.snapshot_to_data(data)
        self.assertEqual(converted["container_metrics"][("app", "web-5d9f-a", "web")]["cpu_m"], 40)

    def test_evaluation_uses_snapshot_and_is_read_only(self):
        from engine.evaluation import run_evaluation

        cluster, _ = account_store.create_agent_cluster(self.admin["tenant_id"], "Cliente X")
        tokens = [current_tenant_id.set(self.admin["tenant_id"]), current_cluster_id.set(cluster["id"]),
                  current_cluster_name.set("Cliente X"), current_cluster_mode.set("agent")]
        try:
            store.save_cluster_snapshot(_snapshot())
            with patch("collectors.kubernetes._run_process", side_effect=AssertionError("kubectl não deve rodar")):
                report = run_evaluation(source="test")
            self.assertEqual(report["cluster"], "Cliente X")
            self.assertEqual(report["summary"]["nodes"], 1)
            self.assertTrue(all(not r["operation"]["executable"] for r in report["recommendations"]))
        finally:
            for var, tok in zip([current_cluster_mode, current_cluster_name, current_cluster_id, current_tenant_id],
                                reversed(tokens)):
                var.reset(tok)

    def test_collector_once_reports_failure_and_success(self):
        with patch.object(snap, "build_snapshot", return_value=_snapshot()), \
             patch.object(snap, "send_snapshot", return_value=(200, {"detail": "ok"})):
            self.assertEqual(snap.run_collector("https://painel.x", "cag_t", once=True), 0)
        with patch.object(snap, "build_snapshot", side_effect=RuntimeError("sem acesso")):
            self.assertEqual(snap.run_collector("https://painel.x", "cag_t", once=True), 1)
        with self.assertRaises(SystemExit):
            snap.run_collector("http://painel.publico.com", "cag_t", once=True)


if __name__ == "__main__":
    unittest.main()
