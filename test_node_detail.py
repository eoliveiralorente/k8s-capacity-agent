import unittest

from analyzers.node_detail import build_node_detail

MI = 1024 ** 2
NODES = {"items": [{"metadata": {"name": "n1", "labels": {"node.kubernetes.io/instance-type": "PRI-2-4"}},
                    "spec": {"taints": [{"key": "dedicated", "value": "db", "effect": "NoSchedule"}]},
                    "status": {"allocatable": {"cpu": "2", "memory": "4Gi", "pods": "110"},
                               "conditions": [{"type": "Ready", "status": "True"},
                                              {"type": "MemoryPressure", "status": "True", "reason": "KubeletHasInsufficientMemory"}],
                               "nodeInfo": {"kubeletVersion": "v1.31.2"}}},
                   {"metadata": {"name": "n2"}, "spec": {}, "status": {"allocatable": {"cpu": "2", "memory": "4Gi"}}}]}
PODS = {"items": [
    {"metadata": {"namespace": "app", "name": "web-5d9f-a", "labels": {"pod-template-hash": "5d9f"},
                  "ownerReferences": [{"kind": "ReplicaSet", "name": "web-5d9f"}]},
     "spec": {"nodeName": "n1", "containers": [{"resources": {"requests": {"cpu": "100m", "memory": "128Mi"}}}]},
     "status": {"phase": "Running", "qosClass": "Burstable", "containerStatuses": [{"restartCount": 2, "state": {"running": {}}}]}},
    {"metadata": {"namespace": "db", "name": "pg-0", "ownerReferences": [{"kind": "StatefulSet", "name": "pg"}]},
     "spec": {"nodeName": "n1", "containers": [{"resources": {}}]},
     "status": {"phase": "Running", "qosClass": "BestEffort"}},
    {"metadata": {"namespace": "app", "name": "outro"}, "spec": {"nodeName": "n2", "containers": []},
     "status": {"phase": "Running"}},
]}


class NodeDetailTest(unittest.TestCase):
    def test_detail(self):
        d = build_node_detail("n1", NODES, PODS, {"n1": {"cpu": "400m", "mem": "2048Mi"}},
                              {"app/web-5d9f-a": {"cpu_m": 30, "mem_b": 90 * MI}, "db/pg-0": {"cpu_m": 200, "mem_b": 1500 * MI}})
        self.assertEqual([p["pod"] for p in d["pods"]], ["pg-0", "web-5d9f-a"])  # ordenado por memória
        self.assertEqual(d["pods"][1]["workload"], "Deployment/web")
        self.assertEqual(d["pods"][0]["workload"], "StatefulSet/pg")
        self.assertEqual(d["pods_without_requests"], 1)
        self.assertEqual(d["conditions_alert"][0]["type"], "MemoryPressure")
        self.assertEqual(d["usage"]["mem_usage_pct"], 50.0)
        self.assertEqual(d["namespaces"][0]["namespace"], "db")
        self.assertIsNone(build_node_detail("nao-existe", NODES, PODS, {}, {}))


if __name__ == "__main__":
    unittest.main()
