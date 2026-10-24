import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from analyzers.costs import estimate
from analyzers.scaling import scaling_recommendations
from executors import kubernetes as k8s_exec

MI = 1024 ** 2


def _series(n, cpu, mem_mi, burst_every=0, burst_cpu=0):
    start = datetime.now(timezone.utc) - timedelta(minutes=15 * n)
    return [((start + timedelta(minutes=15 * i)).isoformat(),
             burst_cpu if burst_every and i % burst_every == 0 else cpu, mem_mi * MI) for i in range(n)]


def _spec(ns="app", kind="Deployment", name="web", cpu=500, mem=512 * MI, replicas=4):
    return {f"{ns}/{kind}/{name}/main": {"namespace": ns, "kind": kind, "name": name, "container": "main",
                                         "cpu_req_m": cpu, "mem_req_b": mem, "cpu_lim_m": 0, "mem_lim_b": 0,
                                         "replicas": replicas}}


def _controllers(replicas=4, labels=None, kind="Deployment", name="web"):
    return {"items": [{"kind": kind, "metadata": {"namespace": "app", "name": name, "labels": labels or {}},
                       "spec": {"replicas": replicas}}]}


class ScalingTest(unittest.TestCase):
    def test_reduce_replicas_keeps_ha_minimum(self):
        recs = scaling_recommendations(_spec(), {"app/Deployment/web/main": _series(20, 50, 100)},
                                       _controllers(6), {})
        self.assertEqual(recs[0]["type"], "REDUCE_REPLICAS")
        params = recs[0]["operation"]["params"]
        self.assertEqual((params["current_replicas"], params["target_replicas"]), (6, 2))
        self.assertTrue(recs[0]["operation"]["executable"])
        self.assertGreater(estimate(recs[0], {}, {"cpu_month": 60, "gb_month": 15}), 0)

    def test_increase_replicas_under_pressure(self):
        recs = scaling_recommendations(_spec(), {"app/Deployment/web/main": _series(20, 480, 200)},
                                       _controllers(3), {})
        self.assertEqual(recs[0]["type"], "INCREASE_REPLICAS")
        self.assertGreater(recs[0]["operation"]["params"]["target_replicas"], 3)
        self.assertLess(estimate(recs[0], {}, {"cpu_month": 60, "gb_month": 15}), 0)

    def test_create_hpa_for_bursty_load(self):
        recs = scaling_recommendations(_spec(), {"app/Deployment/web/main": _series(40, 200, 300, 4, 450)},
                                       _controllers(2), {})
        self.assertEqual(recs[0]["type"], "CREATE_HPA")

    def test_hpa_at_max(self):
        hpas = {"items": [{"metadata": {"namespace": "app", "name": "web"},
                           "spec": {"scaleTargetRef": {"kind": "Deployment", "name": "web"}, "minReplicas": 2,
                                    "maxReplicas": 4}, "status": {"currentReplicas": 4}}]}
        recs = scaling_recommendations(_spec(), {"app/Deployment/web/main": _series(20, 450, 200)},
                                       _controllers(4), hpas)
        self.assertEqual(recs[0]["type"], "HPA_AT_MAX")
        self.assertEqual(recs[0]["operation"]["params"]["target_max"], 6)

    def test_gitops_managed_is_manual(self):
        recs = scaling_recommendations(_spec(), {"app/Deployment/web/main": _series(20, 50, 100)},
                                       _controllers(6, labels={"argocd.argoproj.io/instance": "web"}), {})
        self.assertFalse(recs[0]["operation"]["executable"])
        self.assertIn("GitOps", recs[0]["operation"]["params"]["reason"])

    def test_scale_executor_dry_run_and_rollback(self):
        class Done:
            returncode, stdout, stderr = 0, "deployment.apps/web", ""

        op = {"params": {"namespace": "app", "kind": "Deployment", "name": "web",
                         "current_replicas": 6, "target_replicas": 2}}
        with patch.object(k8s_exec, "_run_process", return_value=Done()) as run:
            result = k8s_exec.execute_scale(op, dry_run=True)
        args = run.call_args[0][0]
        self.assertIn("--dry-run=server", args)
        self.assertIn("--current-replicas=6", args)
        self.assertIn("--replicas=6", result["rollback_command"])
        self.assertFalse(k8s_exec.execute_scale({"params": {**op["params"], "target_replicas": "2; rm"}})["success"])


if __name__ == "__main__":
    unittest.main()
