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

    def test_grace_then_community(self):
        core.save_license_text(_issue(self.key, days=-5))
        self.assertEqual(core.license_status()["state"], "grace")
        self.assertTrue(core.has_feature("execution"))
        core.save_license_text(_issue(self.key, days=-30))
        status = core.license_status()
        self.assertEqual(status["state"], "expired")
        self.assertFalse(core.has_feature("execution"))
        self.assertEqual(status["max_clusters"], 1)


if __name__ == "__main__":
    unittest.main()
