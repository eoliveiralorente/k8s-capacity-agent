import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

from accounts import journal, store
from accounts.rbac import required_role


class JournalTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old = store.DB_PATH
        store.DB_PATH = Path(self.tmp.name) / "a.sqlite3"
        journal._ready = False

    def tearDown(self):
        store.DB_PATH = self.old
        journal._ready = False
        self.tmp.cleanup()

    def test_lifecycle_and_isolation(self):
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        a = journal.create_entry("t1", "c1", "Ana", "pendencia", "Ajustar memória do redis", due_date=yesterday,
                                 link_type="node", link_ref="node-2")
        journal.create_entry("t1", "c1", "Ana", "nota", "Reiniciei o pod api por OOM")
        journal.create_entry("t1", "c2", "Ana", "pendencia", "Outro cluster")
        journal.create_entry("t2", "c1", "Bia", "pendencia", "Outra empresa")

        self.assertEqual(len(journal.list_entries("t1", "c1")), 2)
        s = journal.summary("t1", "c1")
        self.assertEqual((s["open"], s["overdue"]), (1, 1))
        self.assertEqual(s["top"][0]["link_ref"], "node-2")
        self.assertEqual(len(journal.list_entries("t1", "c1", status="atrasadas")), 1)

        done = journal.update_entry("t1", a["id"], "Caio", status="concluida")
        self.assertEqual(done["status"], "concluida")
        self.assertIsNotNone(done["closed_at"])
        self.assertFalse(done["overdue"])
        self.assertIsNone(journal.update_entry("t2", a["id"], "x", status="aberta"))  # outro tenant
        self.assertFalse(journal.delete_entry("t2", a["id"]))
        self.assertTrue(journal.delete_entry("t1", a["id"]))

    def test_validation(self):
        with self.assertRaises(ValueError):
            journal.create_entry("t1", "c1", "Ana", "pendencia", "x", due_date="24/10/2026")
        e = journal.create_entry("t1", "c1", "Ana", "pendencia", "Teste")
        with self.assertRaises(ValueError):
            journal.update_entry("t1", e["id"], "Ana", status="feito")

    def test_rbac(self):
        self.assertEqual(required_role("GET", "/api/journal"), "leitor")
        self.assertEqual(required_role("POST", "/api/journal"), "operador")
        self.assertEqual(required_role("PATCH", "/api/journal/abc"), "operador")
        self.assertEqual(required_role("DELETE", "/api/journal/abc"), "admin")


if __name__ == "__main__":
    unittest.main()
