import unittest

from accounts.rbac import has_role, required_role


class RbacPolicyTest(unittest.TestCase):

    def test_leitor_reads_only(self):
        self.assertTrue(has_role("leitor", required_role("GET", "/api/status")))
        self.assertFalse(has_role("leitor", required_role("POST", "/api/evaluate")))
        self.assertFalse(has_role("leitor", required_role("GET", "/api/cluster/pod-logs")))

    def test_operador_approves_but_not_manage_clusters(self):
        self.assertTrue(has_role("operador", required_role("POST", "/api/recommendations/abc/approve")))
        self.assertTrue(has_role("operador", required_role("POST", "/api/recommendations/abc/reject")))
        self.assertFalse(has_role("operador", required_role("POST", "/api/clusters")))
        self.assertFalse(has_role("operador", required_role("DELETE", "/api/clusters/x1")))

    def test_admin_everything(self):
        for method, path in [("POST", "/api/clusters"), ("DELETE", "/api/clusters/x"),
                             ("POST", "/api/evaluate"), ("PUT", "/api/qualquer")]:
            self.assertTrue(has_role("admin", required_role(method, path)))

    def test_unknown_write_denied_by_default(self):
        self.assertEqual(required_role("POST", "/api/nova-rota"), "admin")
        self.assertFalse(has_role(None, "leitor"))

    def test_logout_for_everyone(self):
        self.assertTrue(has_role("leitor", required_role("POST", "/api/auth/logout")))


if __name__ == "__main__":
    unittest.main()
