import unittest

from analyzers.capacity import analyze_capacity


class GenericKubernetesCapacityTests(unittest.TestCase):
    def test_groups_nodes_by_role_and_includes_standard_metadata(self):
        nodes = {
            "items": [
                {
                    "metadata": {
                        "name": "control-0",
                        "labels": {
                            "node-role.kubernetes.io/master": "",
                            "node.kubernetes.io/instance-type": "ST-1-8",
                        },
                    },
                    "status": {
                        "allocatable": {"cpu": "2", "memory": "8Gi"},
                        "nodeInfo": {"kubeletVersion": "v1.31.2"},
                        "conditions": [{"type": "Ready", "status": "True"}],
                    },
                },
                {
                    "metadata": {
                        "name": "worker-0",
                        "labels": {
                            "magnum.openstack.org/role": "worker",
                            "node.kubernetes.io/instance-type": "PRI-1-2",
                        },
                    },
                    "status": {
                        "allocatable": {"cpu": "4", "memory": "16Gi"},
                        "nodeInfo": {"kubeletVersion": "v1.31.2"},
                        "conditions": [{"type": "Ready", "status": "True"}],
                    },
                },
            ]
        }

        result = analyze_capacity(nodes, {"items": []}, {}, {})

        self.assertEqual(set(result), {"master", "worker"})
        self.assertEqual(result["master"]["capacity"]["node_count"], 1)
        self.assertEqual(result["worker"]["capacity"]["node_count"], 1)
        self.assertEqual(result["master"]["kubernetes"]["status"], "Ready")
        self.assertEqual(result["master"]["kubernetes"]["version"], "v1.31.2")
        self.assertEqual(result["master"]["kubernetes"]["machine_type"], "ST-1-8")
        self.assertEqual(result["worker"]["kubernetes"]["machine_type"], "PRI-1-2")

    def test_non_ready_node_marks_its_group_degraded(self):
        nodes = {
            "items": [
                {
                    "metadata": {"name": "worker-0", "labels": {}},
                    "status": {
                        "allocatable": {},
                        "conditions": [{"type": "Ready", "status": "False"}],
                    },
                }
            ]
        }

        result = analyze_capacity(nodes, {"items": []}, {}, {})

        self.assertEqual(result["worker"]["kubernetes"]["status"], "NotReady")


if __name__ == "__main__":
    unittest.main()
