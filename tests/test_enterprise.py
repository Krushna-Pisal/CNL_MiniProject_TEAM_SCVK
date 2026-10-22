import sys
import unittest
from pathlib import Path
import networkx as nx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from enterprise_config import HOSTS, policy_allows
from enterprise_topology import build_enterprise_topology
from controller_sim import select_flow_route
from topology import build_topology
sys.path.insert(0, str(ROOT / "mininet_sdn"))
from common import update_link_state, validate_enterprise_source


class EnterpriseDesignTests(unittest.TestCase):
    def test_packet_visualization_route_matches_static_router(self):
        graph = build_enterprise_topology()
        actual = select_flow_route(graph, "h4", "h9", "static")
        expected = nx.shortest_path(graph, "h4", "h9", weight="base_delay_ms")
        self.assertEqual(actual, expected)

    def test_packet_visualization_failure_route_avoids_failed_link(self):
        graph = build_enterprise_topology()
        route = select_flow_route(graph, "h4", "h9", "adaptive",
                                  failed_links=[("s5", "s7")])
        self.assertFalse(any(set(pair) == {"s5", "s7"}
                             for pair in zip(route[:-1], route[1:])))

    def test_adaptive_packet_route_responds_to_injected_congestion(self):
        graph = build_enterprise_topology()
        normal = select_flow_route(graph, "h4", "h9", "adaptive", priority=3)
        congested = select_flow_route(
            graph, "h4", "h9", "adaptive", priority=3,
            link_load_mbps={frozenset(("s5", "s7")): graph["s5"]["s7"]["capacity_mbps"]},
        )
        self.assertIn({"s5", "s7"}, [set(e) for e in zip(normal[:-1], normal[1:])])
        self.assertNotIn({"s5", "s7"}, [set(e) for e in zip(congested[:-1], congested[1:])])

    def test_packet_visualization_handles_disconnected_and_unknown_nodes(self):
        graph = nx.Graph()
        graph.add_edge("h1", "s1", base_delay_ms=1, capacity_mbps=10)
        graph.add_node("h2")
        with self.assertRaises(nx.NetworkXNoPath):
            select_flow_route(graph, "h1", "h2")
        with self.assertRaises(nx.NodeNotFound):
            select_flow_route(graph, "h1", "missing")

    def test_original_topology_remains_unchanged(self):
        baseline = build_topology()
        self.assertEqual(sum(d["kind"] == "switch" for _, d in baseline.nodes(data=True)), 8)
        self.assertEqual(sum(d["kind"] == "host" for _, d in baseline.nodes(data=True)), 6)
        self.assertEqual(baseline.number_of_edges(), 18)

    def test_enterprise_extends_switches_and_has_vlan_hosts(self):
        graph = build_enterprise_topology()
        self.assertEqual(sum(d["kind"] == "switch" for _, d in graph.nodes(data=True)), 8)
        self.assertEqual(sum(d["kind"] == "host" for _, d in graph.nodes(data=True)), 14)
        self.assertEqual({d["site"] for n, d in graph.nodes(data=True) if d["kind"] == "switch"},
                         {"Headquarters", "Branch Office 1", "Branch Office 2"})
        self.assertTrue(all(HOSTS[h]["vlan"] for h in HOSTS))

    def test_security_policy_allow_and_deny(self):
        cases = [
            ("h2", "h11", "tcp", 8443, True),
            ("h4", "h9", "tcp", 80, True),
            ("h6", "h8", "udp", 53, True),
            ("h4", "h11", "tcp", 8443, False),
            ("h2", "h12", "tcp", 22, False),
            ("h4", "h6", "icmp", 0, True),
            ("h4", "h6", "tcp", 443, False),
            ("h9", "h4", "tcp", 0, True, 80),
            ("h12", "h3", "icmp", 0, True),
        ]
        for case in cases:
            src, dst, protocol, dst_port, expected, *src_port = case
            with self.subTest(case=case):
                self.assertEqual(policy_allows(HOSTS[src], HOSTS[dst], protocol, dst_port,
                                               src_port[0] if src_port else 0), expected)

    def test_link_failure_has_alternate_path_avoiding_failed_link(self):
        graph = build_enterprise_topology()
        failed = ("s5", "s8")
        initial = nx.shortest_path(graph, "h4", "h6", weight="base_delay_ms")
        self.assertTrue(any(set(pair) == set(failed) for pair in zip(initial[:-1], initial[1:])))
        graph.remove_edge(*failed)
        alternate = nx.shortest_path(graph, "h4", "h6", weight="base_delay_ms")
        self.assertFalse(any(set(pair) == set(failed) for pair in zip(alternate[:-1], alternate[1:])))

    def test_source_identity_is_bound_to_access_port_and_vlan(self):
        config = {
            "mode": "enterprise",
            "hosts": [{"ip": "10.10.10.10", "mac": "00:00:00:00:00:01",
                       "dpid": 1, "port": 1, "vlan": 10}],
            "links": [{"dpid1": 1, "port1": 2, "dpid2": 2, "port2": 2}],
        }
        self.assertTrue(validate_enterprise_source(
            config, 1, 1, "10.10.10.10", "00:00:00:00:00:01", None)[0])
        self.assertFalse(validate_enterprise_source(
            config, 1, 1, "10.10.10.10", "00:00:00:00:00:02", 10)[0])
        self.assertFalse(validate_enterprise_source(
            config, 1, 1, "10.10.10.10", "00:00:00:00:00:01", 20)[0])
        self.assertTrue(validate_enterprise_source(
            config, 1, 2, "10.10.10.10", "02:00:00:00:00:01", 10)[0])

    def test_link_state_events_remove_restore_and_ignore_duplicates(self):
        graph = nx.Graph()
        graph.add_edge(1, 2, capacity_mbps=50, delay_ms=2, port_map={1: 5, 2: 7})
        config = {"links": [{"dpid1": 1, "port1": 5, "dpid2": 2, "port2": 7,
                             "capacity_mbps": 50, "delay_ms": 2}]}
        self.assertEqual(update_link_state(graph, config, 1, 5, False), (1, 2))
        self.assertFalse(graph.has_edge(1, 2))
        self.assertIsNone(update_link_state(graph, config, 2, 7, False))
        self.assertEqual(update_link_state(graph, config, 2, 7, True), (1, 2))
        self.assertTrue(graph.has_edge(1, 2))
        self.assertIsNone(update_link_state(graph, config, 2, 7, True))


if __name__ == "__main__":
    unittest.main()
