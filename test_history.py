import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from accounts import store as account_store
from analyzers.history import summarize_history
from approval import store
from engine.evaluation import apply_history
from tenant_context import current_cluster_id, current_tenant_id


def _capacity(cpu, mem):
    return {"w": {"capacity": {"node_count": 3},
                  "metrics": {"cpu_usage_vs_alloc_pct": cpu, "mem_usage_vs_alloc_pct": mem,
                              "cpu_req_vs_alloc_pct": 20, "mem_req_vs_alloc_pct": 15}}}


class HistoryTest(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.patches = [patch.object(account_store, "DB_PATH", Path(self.tmp.name) / "a.sqlite3"),
                        patch.object(store, "STATE_DIR", self.tmp.name)]
        for p in self.patches:
            p.start()
        self.tokens = [current_tenant_id.set("t1"), current_cluster_id.set("c1")]

    def tearDown(self):
        current_cluster_id.reset(self.tokens[1])
        current_tenant_id.reset(self.tokens[0])
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()

    def _fill(self, values):
        start = datetime.now(timezone.utc) - timedelta(hours=len(values))
        for i, (cpu, mem) in enumerate(values):
            store.save_metric_samples(_capacity(cpu, mem), (start + timedelta(hours=i)).isoformat())

    def test_summary_peak_and_confidence(self):
        self._fill([(5, 20)] * 20 + [(65, 30)])
        h = summarize_history(store.load_metric_samples())["w"]
        self.assertEqual(h["samples"], 21)
        self.assertEqual(h["cpu_usage_max"], 65.0)
        self.assertEqual(h["confidence"], "media")

    def test_reduction_suppressed_by_peak(self):
        self._fill([(5, 20)] * 20 + [(65, 30)])
        history = summarize_history(store.load_metric_samples())
        recs = [{"id": "r1", "type": "UNDERUTILIZED_POOL", "pool": "w", "action": "Reduzir"}]
        kept, suppressed = apply_history(recs, history)
        self.assertEqual(kept, [])
        self.assertEqual(suppressed[0]["id"], "r1")

    def test_reduction_kept_when_history_is_low(self):
        self._fill([(5, 20)] * 20)
        history = summarize_history(store.load_metric_samples())
        recs = [{"id": "r1", "type": "UNDERUTILIZED_POOL", "pool": "w", "action": "Reduzir"}]
        kept, _ = apply_history(recs, history)
        self.assertEqual(len(kept), 1)
        self.assertIn("pico CPU 5.0%", kept[0]["action"])


if __name__ == "__main__":
    unittest.main()
