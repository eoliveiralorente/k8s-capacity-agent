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


if __name__ == "__main__":
    unittest.main()
