import io
import json
import logging
import os
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from accounts import store as account_store
from approval import store
from support import bundle, health, logbuffer


class SupportTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.patches = [patch.object(account_store, "DB_PATH", Path(self.tmp.name) / "a.sqlite3"),
                        patch.object(store, "STATE_DIR", self.tmp.name),
                        patch.dict(os.environ, {"CAPACITY_AGENT_ENCRYPTION_KEY": "", "CAPACITY_AGENT_SMTP_PASSWORD": "senha-smtp",
                                                "CAPACITY_AGENT_PUBLIC_URL": "https://painel.x"})]
        for p in self.patches:
            p.start()
        os.environ.pop("CAPACITY_AGENT_ENCRYPTION_KEY", None)
        account_store.initialize_database()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()

    def test_health_reports_checks(self):
        with patch.object(health, "_kubectl", return_value=(True, "clientVersion:\n  gitVersion: v1.31.0")):
            result = health.run_checks(include_cluster=False)
        names = {c["name"] for c in result["checks"]}
        self.assertTrue({"Banco de dados", "Chave de criptografia", "Licença", "kubectl"} <= names)
        self.assertIn(result["status"], ("ok", "aviso", "erro"))

    def test_license_check_levels(self):
        base = {"plan": "profissional", "message": "m", "days_left": 200}
        self.assertEqual(health._license_check({**base, "state": "valid"})["status"], "ok")
        self.assertEqual(health._license_check({**base, "state": "valid", "days_left": 10})["status"], "aviso")
        self.assertEqual(health._license_check({**base, "state": "grace"})["status"], "aviso")
        for state in ("community", "expired", "invalid"):
            check = health._license_check({**base, "plan": "community", "state": state, "days_left": None})
            self.assertEqual(check["status"], "aviso")
            self.assertIn("Licença", check["hint"])

    def test_bundle_has_no_secrets(self):
        logbuffer.install()
        logging.getLogger("capacity-agent").warning("token=abcdefghijklmnopqrstuvwxyz0123 do usuario eu@x.com")
        with patch.object(health, "_kubectl", return_value=(True, "ok")):
            data = bundle.build_bundle()
        archive = zipfile.ZipFile(io.BytesIO(data))
        names = set(archive.namelist())
        self.assertTrue({"LEIA-ME.txt", "health.json", "environment.json", "logs.txt", "license.json"} <= names)
        everything = b"".join(archive.read(n) for n in names)
        self.assertNotIn(b"senha-smtp", everything)
        self.assertNotIn(b"abcdefghijklmnopqrstuvwxyz0123", everything)
        self.assertNotIn(b"eu@x.com", everything)
        self.assertFalse(any(n.endswith((".sqlite3", ".key", ".pem")) for n in names))
        env = json.loads(archive.read("environment.json"))["variables"]
        self.assertEqual(env["CAPACITY_AGENT_SMTP_PASSWORD"], "[OCULTO]")


if __name__ == "__main__":
    unittest.main()
