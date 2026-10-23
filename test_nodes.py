import unittest

from analyzers.nodes import analyze_nodes


def _node(name, role="worker"):
    labels = {"magnum.openstack.org/nodegroup": f"default-{role}", "magnum.openstack.org/role": role}
    if role == "master":
        labels["node-role.kubernetes.io/master"] = ""
    return {"metadata": {"name": name, "labels": labels},
            "status": {"allocatable": {"cpu": "2", "memory": "4Gi", "pods": "110"},
                       "conditions": [{"type": "Ready", "status": "True"}]}}


def _pod(node, cpu="500m", mem="1Gi", phase="Running"):
    return {"spec": {"nodeName": node, "containers": [{"resources": {"requests": {"cpu": cpu, "memory": mem}}}]},
            "status": {"phase": phase}}


class NodesUsageTest(unittest.TestCase):

    def test_percentages_per_node(self):
        nodes = {"items": [_node("w1"), _node("m1", "master")]}
        pods = {"items": [_pod("w1"), _pod("w1"), _pod("w1", phase="Succeeded")]}
        metrics = {"w1": {"cpu": "200m", "mem": "2048Mi"}}
        result = {n["name"]: n for n in analyze_nodes(nodes, pods, metrics)}
        w1 = result["w1"]
        self.assertEqual(w1["pod_count"], 2)
        self.assertEqual(w1["cpu_req_pct"], 50.0)
        self.assertEqual(w1["mem_req_pct"], 50.0)
        self.assertEqual(w1["cpu_usage_pct"], 10.0)
        self.assertEqual(w1["mem_usage_pct"], 50.0)
        self.assertTrue(result["m1"]["control_plane"])
        self.assertIsNone(result["m1"]["cpu_usage_pct"])


if __name__ == "__main__":
    unittest.main()
