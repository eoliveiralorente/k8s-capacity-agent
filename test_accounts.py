import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cryptography.fernet import Fernet

from accounts import store
from approval import store as approval_store
from tenant_context import current_cluster_id, current_tenant_id


class AccountStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temp_dir.name) / "accounts.sqlite3"
        self.database_patch = patch.object(store, "DB_PATH", self.database_path)
        self.database_patch.start()
        self.key_patch = patch.dict(
            os.environ,
            {"CAPACITY_AGENT_ENCRYPTION_KEY": Fernet.generate_key().decode("ascii")},
        )
        self.key_patch.start()
        store.initialize_database()

    def tearDown(self):
        self.key_patch.stop()
        self.database_patch.stop()
        self.temp_dir.cleanup()

    def register(self, email, company):
        return store.register_account(company, "Test User", email, "correct-horse-battery")

    def test_password_hash_and_authentication(self):
        user = self.register("owner@example.test", "Example Ltd")

        self.assertEqual(user["email"], "owner@example.test")
        self.assertIsNotNone(store.authenticate("OWNER@example.test", "correct-horse-battery"))
        self.assertIsNone(store.authenticate("owner@example.test", "wrong-password"))

        with sqlite3.connect(self.database_path) as connection:
            password_hash = connection.execute(
                "SELECT password_hash FROM users WHERE id = ?", (user["id"],)
            ).fetchone()[0]
        self.assertTrue(password_hash.startswith("$scrypt$"))
        self.assertNotIn("correct-horse-battery", password_hash)

    def test_kubeconfig_is_encrypted_and_scoped_to_tenant(self):
        first = self.register("first@example.test", "First Company")
        second = self.register("second@example.test", "Second Company")
        kubeconfig = b"apiVersion: v1\nusers:\n- name: private-token\n"

        cluster = store.create_cluster(first["tenant_id"], "Production", kubeconfig, "prod", 5)

        with sqlite3.connect(self.database_path) as connection:
            ciphertext = connection.execute(
                "SELECT kubeconfig_ciphertext FROM clusters WHERE id = ?", (cluster["id"],)
            ).fetchone()[0]
        self.assertNotIn(kubeconfig, ciphertext)
        self.assertEqual(
            store.decrypt_cluster_kubeconfig(first["tenant_id"], cluster["id"]),
            kubeconfig,
        )
        self.assertIsNone(store.get_cluster(second["tenant_id"], cluster["id"]))
        self.assertEqual(store.list_clusters(second["tenant_id"]), [])

    def test_missing_encryption_key_is_generated_and_persisted(self):
        with patch.dict(os.environ, {"CAPACITY_AGENT_ENCRYPTION_KEY": ""}):
            store.initialize_database()
            key_path = self.database_path.with_name("encryption.key")
            saved_key = key_path.read_bytes()
            ciphertext = store._fernet()[0].encrypt(b"test kubeconfig")

            store.initialize_database()

            self.assertEqual(key_path.read_bytes(), saved_key)
            self.assertEqual(store._fernet()[0].decrypt(ciphertext), b"test kubeconfig")
            if os.name == "posix":
                self.assertEqual(key_path.stat().st_mode & 0o777, 0o600)

    def test_invalid_configured_encryption_key_is_rejected(self):
        with patch.dict(os.environ, {"CAPACITY_AGENT_ENCRYPTION_KEY": "invalid"}):
            with self.assertRaisesRegex(
                RuntimeError,
                r"CAPACITY_AGENT_ENCRYPTION_KEY inválida.*Fernet.generate_key",
            ):
                store._fernet()

    def test_session_token_is_hashed_and_revocable(self):
        user = self.register("session@example.test", "Session Company")
        token, _ = store.create_session(user["id"])

        with sqlite3.connect(self.database_path) as connection:
            saved_token_hash = connection.execute(
                "SELECT token_hash FROM sessions WHERE user_id = ?", (user["id"],)
            ).fetchone()[0]
        self.assertNotEqual(saved_token_hash, token)
        self.assertEqual(store.get_session(token)["tenant_id"], user["tenant_id"])

        store.delete_session(token)
        self.assertIsNone(store.get_session(token))

    def test_state_path_includes_tenant_and_cluster(self):
        tenant_token = current_tenant_id.set("tenant-a")
        cluster_token = current_cluster_id.set("cluster-b")
        state_dir_patch = patch.object(approval_store, "STATE_DIR", self.temp_dir.name)
        state_dir_patch.start()
        try:
            path = approval_store._state_path("audit.log")
        finally:
            state_dir_patch.stop()
            current_cluster_id.reset(cluster_token)
            current_tenant_id.reset(tenant_token)

        self.assertIn(os.path.join("tenants", "tenant-a", "cluster-b"), path)


if __name__ == "__main__":
    unittest.main()
