import os
import tempfile
import unittest
from pathlib import Path

from accounts import store


class InviteFlowTest(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old_db = store.DB_PATH
        store.DB_PATH = Path(self.tmp.name) / "accounts.sqlite3"
        os.environ.setdefault("CAPACITY_AGENT_ENCRYPTION_KEY", "")
        self.admin = store.register_account("Empresa", "Admin", "admin@x.com", "senha-muito-forte-1")

    def tearDown(self):
        store.DB_PATH = self.old_db
        self.tmp.cleanup()

    def test_invite_creates_user_with_role_in_same_tenant(self):
        token, _ = store.create_invite(self.admin["tenant_id"], "operador", "Admin")
        user = store.accept_invite(token, "Op", "op@x.com", "senha-muito-forte-2")
        self.assertEqual(user["role"], "operador")
        self.assertEqual(user["tenant_id"], self.admin["tenant_id"])
        with self.assertRaises(store.InviteError):
            store.accept_invite(token, "Outro", "outro@x.com", "senha-muito-forte-3")

    def test_invite_bound_to_email(self):
        token, _ = store.create_invite(self.admin["tenant_id"], "leitor", "Admin", "certo@x.com")
        with self.assertRaises(store.InviteError):
            store.accept_invite(token, "Errado", "errado@x.com", "senha-muito-forte-4")

    def test_last_admin_is_protected(self):
        with self.assertRaises(store.LastAdminError):
            store.set_user_role(self.admin["tenant_id"], self.admin["id"], "leitor")
        with self.assertRaises(store.LastAdminError):
            store.delete_user(self.admin["tenant_id"], self.admin["id"])

    def test_role_change_revokes_sessions(self):
        token, _ = store.create_invite(self.admin["tenant_id"], "operador", "Admin")
        user = store.accept_invite(token, "Op", "op2@x.com", "senha-muito-forte-5")
        session_token, _ = store.create_session(user["id"])
        self.assertEqual(store.get_session(session_token)["role"], "operador")
        store.set_user_role(self.admin["tenant_id"], user["id"], "leitor")
        self.assertIsNone(store.get_session(session_token))


if __name__ == "__main__":
    unittest.main()
