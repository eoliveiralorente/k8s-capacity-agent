import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from accounts import store
from collectors import kubernetes as k8s
from tenant_context import current_cluster_id, current_tenant_id


class SelfHostedTest(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = patch.object(store, "DB_PATH", Path(self.tmp.name) / "a.sqlite3")
        self.db.start()

    def tearDown(self):
        self.db.stop()
        self.tmp.cleanup()

    def test_incluster_cluster_created_once(self):
        self.assertEqual(store.count_tenants(), 0)
        admin = store.register_account("Cliente", "Admin", "a@x.com", "senha-muito-forte-1")
        self.assertEqual(store.count_tenants(), 1)
        first = store.ensure_incluster_cluster(admin["tenant_id"], "Produção")
        second = store.ensure_incluster_cluster(admin["tenant_id"], "Produção")
        self.assertEqual(first, second)
        clusters = store.list_clusters(admin["tenant_id"])
        self.assertEqual([(c["name"], c["mode"]) for c in clusters], [("Produção", "incluster")])

    def test_incluster_uses_serviceaccount_not_kubeconfig(self):
        admin = store.register_account("Cliente", "Admin", "b@x.com", "senha-muito-forte-1")
        cluster_id = store.ensure_incluster_cluster(admin["tenant_id"], "Produção")
        tokens = [current_tenant_id.set(admin["tenant_id"]), current_cluster_id.set(cluster_id)]
        try:
            with patch.dict(os.environ, {}, clear=False), patch.object(k8s, "KUBECONFIG", None):
                os.environ.pop("KUBECONFIG", None)
                with k8s._command_env() as env:
                    self.assertNotIn("KUBECONFIG", env)
        finally:
            current_cluster_id.reset(tokens[1])
            current_tenant_id.reset(tokens[0])


if __name__ == "__main__":
    unittest.main()
