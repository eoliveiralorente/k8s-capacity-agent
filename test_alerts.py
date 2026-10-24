import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from accounts import store as account_store
from alerts import dispatch, notify
from alerts.rules import build_alerts, filter_by_severity
from approval import store
from tenant_context import current_cluster_id, current_tenant_id

REPORT = {
    "cluster": "Lab",
    "nodes_usage": [{"name": "n1", "pool": "w", "ready": True, "mem_usage_pct": 93.0, "cpu_usage_pct": 20.0,
                     "mem_req_pct": 10.0}],
    "unhealthy_pods": [{"namespace": "app", "name": "api-1", "status": "CrashLoopBackOff", "restarts": 7}],
    "summary": {"pending_pods": 0},
    "recommendations": [{"id": "r1", "severity": "LOW", "status": "pending", "type": "X", "action": ""}],
    "decision": {"reasons": []},
}


class AlertsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.patches = [patch.object(account_store, "DB_PATH", Path(self.tmp.name) / "a.sqlite3"),
                        patch.object(store, "STATE_DIR", self.tmp.name),
                        patch("licensing.core.has_feature", return_value=True)]
        for p in self.patches:
            p.start()
        self.admin = account_store.register_account("E", "A", "a@x.com", "senha-muito-forte-1")
        self.tokens = [current_tenant_id.set(self.admin["tenant_id"]), current_cluster_id.set("c1")]

    def tearDown(self):
        current_cluster_id.reset(self.tokens[1])
        current_tenant_id.reset(self.tokens[0])
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()

    def test_rules(self):
        alerts = build_alerts(REPORT)
        keys = {a["key"] for a in alerts}
        self.assertEqual(keys, {"node-mem:n1", "pod:app/api-1"})
        self.assertEqual(len(filter_by_severity(alerts, "HIGH")), 2)

    def test_dedup_reminder_and_resolve(self):
        now = datetime.now(timezone.utc)
        alerts = build_alerts(REPORT)
        first = store.reconcile_alert_state(alerts, now=now)
        self.assertEqual({i["state"] for i in first}, {"new"})
        self.assertEqual(store.reconcile_alert_state(alerts, now=now + timedelta(hours=1)), [])
        later = store.reconcile_alert_state(alerts, now=now + timedelta(hours=7))
        self.assertEqual({i["state"] for i in later}, {"reminder"})
        resolved = store.reconcile_alert_state(alerts[:1], now=now + timedelta(hours=8))
        self.assertEqual([(i["key"], i["state"]) for i in resolved], [("pod:app/api-1", "resolved")])

    def test_settings_encrypted_and_dispatch(self):
        account_store.save_alert_settings(self.admin["tenant_id"], slack_url="https://hooks.slack.com/services/SEGREDO",
                                          teams_url="https://teams.example/hook")
        raw = (Path(self.tmp.name) / "a.sqlite3").read_bytes()
        self.assertNotIn(b"SEGREDO", raw)
        sent = []
        with patch.object(notify, "_post_json", side_effect=lambda url, payload, timeout=15: sent.append((url, payload)) or 200):
            items = dispatch.process_alerts(REPORT)
        self.assertEqual(len(items), 2)
        self.assertEqual({u for u, _ in sent}, {"https://hooks.slack.com/services/SEGREDO", "https://teams.example/hook"})
        slack_payload = next(p for u, p in sent if "slack" in u)
        self.assertIn("CrashLoopBackOff", slack_payload["text"])
        teams_payload = next(p for u, p in sent if "teams" in u)
        self.assertEqual(teams_payload["attachments"][0]["contentType"], "application/vnd.microsoft.card.adaptive")


if __name__ == "__main__":
    unittest.main()
