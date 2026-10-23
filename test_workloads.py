import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from analyzers.workloads import MI, collect_workloads, rightsizing_recommendations, workload_owner
from executors import kubernetes as k8s_exec


def _pod(ns="app", name="web-5d9f-abc", rs="web-5d9f", cpu="500m", mem="512Mi", phase="Running"):
    return {"metadata": {"namespace": ns, "name": name, "labels": {"pod-template-hash": "5d9f"},
                         "ownerReferences": [{"kind": "ReplicaSet", "name": rs}]},
            "spec": {"containers": [{"name": "web", "resources": {"requests": {"cpu": cpu, "memory": mem}}}]},
            "status": {"phase": phase}}


def _series(n, cpu_m, mem_mi):
    start = datetime.now(timezone.utc) - timedelta(minutes=15 * n)
    return [((start + timedelta(minutes=15 * i)).isoformat(), cpu_m, mem_mi * MI) for i in range(n)]


class WorkloadTest(unittest.TestCase):

    def test_owner_from_replicaset(self):
        self.assertEqual(workload_owner(_pod()), ("Deployment", "web"))

    def test_collect_uses_max_across_replicas(self):
        pods = {"items": [_pod(name="web-5d9f-a"), _pod(name="web-5d9f-b")]}
        metrics = {("app", "web-5d9f-a", "web"): {"cpu_m": 30, "mem_b": 100 * MI},
                   ("app", "web-5d9f-b", "web"): {"cpu_m": 60, "mem_b": 80 * MI}}
        samples, specs = collect_workloads(pods, metrics)
        self.assertEqual(samples["app/Deployment/web/web"], {"cpu_m": 60, "mem_b": 100 * MI})
        self.assertEqual(specs["app/Deployment/web/web"]["cpu_req_m"], 500)

    def test_reduction_is_executable_with_enough_history(self):
        _, specs = collect_workloads({"items": [_pod()]}, {})
        recs = rightsizing_recommendations(specs, {"app/Deployment/web/web": _series(20, 40, 100)})
        self.assertEqual(len(recs), 1)
        rec = recs[0]
        self.assertEqual(rec["type"], "RIGHTSIZE_REQUESTS")
        self.assertTrue(rec["operation"]["executable"])
        self.assertEqual(rec["operation"]["params"]["target"], {"cpu": "55m", "memory": "130Mi"})

    def test_low_confidence_and_protected_namespace_are_manual(self):
        _, specs = collect_workloads({"items": [_pod(), _pod(ns="kube-system")]}, {})
        history = {"app/Deployment/web/web": _series(3, 40, 100),
                   "kube-system/Deployment/web/web": _series(20, 40, 100)}
        recs = rightsizing_recommendations(specs, history)
        self.assertTrue(all(not r["operation"]["executable"] for r in recs))

    def test_memory_pressure_is_high_increase(self):
        _, specs = collect_workloads({"items": [_pod(mem="128Mi")]}, {})
        recs = rightsizing_recommendations(specs, {"app/Deployment/web/web": _series(20, 100, 125)})
        self.assertEqual(recs[0]["type"], "INCREASE_REQUESTS")
        self.assertEqual(recs[0]["severity"], "HIGH")

    def test_executor_builds_safe_dry_run_command(self):
        op = {"kind": "k8s_set_resources", "params": {
            "namespace": "app", "kind": "Deployment", "name": "web", "container": "web",
            "current": {"cpu": "500m", "memory": "512Mi"}, "target": {"cpu": "55m", "memory": "130Mi"}}}

        class Done:
            returncode, stdout, stderr = 0, "deployment.apps/web", ""

        with patch.object(k8s_exec, "_run_process", return_value=Done()) as run:
            result = k8s_exec.execute_set_resources(op, dry_run=True)
        args = run.call_args[0][0]
        self.assertIn("--dry-run=server", args)
        self.assertIn("--requests=cpu=55m,memory=130Mi", args)
        self.assertTrue(result["success"])
        self.assertIn("--requests=cpu=500m,memory=512Mi", result["rollback_command"])

    def test_executor_rejects_injection(self):
        op = {"params": {"namespace": "app; rm -rf /", "kind": "Deployment", "name": "web",
                         "container": "web", "target": {"cpu": "55m", "memory": "130Mi"}}}
        self.assertFalse(k8s_exec.execute_set_resources(op)["success"])


if __name__ == "__main__":
    unittest.main()
