import json
import subprocess
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from collectors.kubernetes import get_cluster_pod_logs, get_cluster_pods


class ClusterPodsCollectorTests(unittest.TestCase):
    def test_maps_ready_restarts_status_namespace_and_age(self):
        pod_data = {
            "items": [
                {
                    "metadata": {
                        "namespace": "dev",
                        "name": "api-0",
                        "creationTimestamp": "2026-10-09T10:00:00Z",
                    },
                    "spec": {
                        "containers": [{"name": "api"}, {"name": "sidecar"}],
                        "initContainers": [{"name": "init-db"}],
                    },
                    "status": {
                        "phase": "Running",
                        "containerStatuses": [
                            {"ready": True, "restartCount": 1},
                            {"ready": False, "restartCount": 2},
                        ],
                    },
                },
                {
                    "metadata": {"namespace": "debug", "name": "broken"},
                    "spec": {"containers": [{"name": "app"}]},
                    "status": {
                        "phase": "Running",
                        "containerStatuses": [{
                            "ready": False,
                            "restartCount": 5,
                            "state": {"waiting": {"reason": "CrashLoopBackOff"}},
                        }],
                    },
                },
                {
                    "metadata": {"namespace": "jobs", "name": "finished"},
                    "spec": {"containers": [{"name": "job"}]},
                    "status": {"phase": "Succeeded", "containerStatuses": []},
                },
            ]
        }
        result = SimpleNamespace(returncode=0, stdout=json.dumps(pod_data), stderr="")

        with patch("collectors.kubernetes._run_process", return_value=result) as run_process:
            pods = get_cluster_pods()

        self.assertEqual(run_process.call_args.args[0], ["kubectl", "get", "pods", "--all-namespaces", "-o", "json"])
        self.assertEqual(pods[0], {
            "namespace": "dev",
            "name": "api-0",
            "containers": ["api", "sidecar"],
            "init_containers": ["init-db"],
            "ready": "1/2",
            "status": "Running",
            "restarts": 3,
            "created_at": "2026-10-09T10:00:00Z",
        })
        self.assertEqual(pods[1]["status"], "CrashLoopBackOff")
        self.assertEqual(pods[1]["restarts"], 5)
        self.assertEqual(pods[2]["status"], "Completed")

    def test_reports_kubectl_failure(self):
        result = SimpleNamespace(returncode=1, stdout="", stderr="forbidden")

        with patch("collectors.kubernetes._run_process", return_value=result):
            with self.assertRaisesRegex(RuntimeError, "forbidden"):
                get_cluster_pods()

    def test_reads_limited_timestamped_container_logs(self):
        result = SimpleNamespace(returncode=0, stdout="2026-10-16T00:00:00Z started\n", stderr="")

        with patch("collectors.kubernetes._run_process", return_value=result) as run_process:
            logs = get_cluster_pod_logs("dev", "api-0", "api", previous=True)

        self.assertEqual(logs, result.stdout)
        self.assertEqual(
            run_process.call_args.args[0],
            [
                "kubectl", "logs", "api-0",
                "--namespace", "dev",
                "--tail=200",
                "--limit-bytes=262144",
                "--timestamps",
                "--container", "api",
                "--previous",
            ],
        )
        self.assertEqual(run_process.call_args.kwargs["timeout"], 20)

    def test_reports_kubectl_log_failure(self):
        result = SimpleNamespace(returncode=1, stdout="", stderr="container is waiting to start")

        with patch("collectors.kubernetes._run_process", return_value=result):
            with self.assertRaisesRegex(RuntimeError, "container is waiting to start"):
                get_cluster_pod_logs("dev", "api-0")

    def test_reports_log_timeout(self):
        with patch(
            "collectors.kubernetes._run_process",
            side_effect=subprocess.TimeoutExpired(["kubectl", "logs"], 20),
        ):
            with self.assertRaisesRegex(RuntimeError, "Tempo esgotado"):
                get_cluster_pod_logs("dev", "api-0")


if __name__ == "__main__":
    unittest.main()
