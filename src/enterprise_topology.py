"""Enterprise topology built by extending the original eight-switch graph."""

from __future__ import annotations

import networkx as nx

from enterprise_config import HOSTS
from topology import build_topology


def build_enterprise_topology() -> nx.Graph:
    """Return HQ + two-branch graph with 14 VLAN-assigned hosts.

    Original switches are retained. The baseline's six host attachment edges
    are replaced only in this opt-in enterprise graph; baseline `build_topology`
    and its callers remain unchanged.
    """
    graph = build_topology()
    for host in [node for node, data in graph.nodes(data=True) if data.get("kind") == "host"]:
        graph.remove_node(host)

    site_by_switch = {
        "s1": "Headquarters", "s2": "Headquarters", "s3": "Headquarters", "s4": "Headquarters",
        "s5": "Branch Office 1", "s7": "Branch Office 1",
        "s6": "Branch Office 2", "s8": "Branch Office 2",
    }
    for switch, site in site_by_switch.items():
        graph.nodes[switch]["site"] = site

    # Add separate inter-site paths while retaining all original core links.
    redundant_links = [
        ("s2", "s7", 80, 3),  # alternate HQ <-> Branch 1 path
        ("s4", "s6", 100, 2), # alternate HQ <-> Branch 2 path
        ("s3", "s8", 80, 3),  # second Branch 2 handoff
    ]
    for u, v, capacity, delay in redundant_links:
        graph.add_edge(u, v, capacity_mbps=capacity, base_delay_ms=delay, kind="core", enterprise=True)

    for name, config in HOSTS.items():
        graph.add_node(
            name, kind="host", site=config["site"], department=config["role"],
            vlan=config["vlan"], subnet=config["subnet"], ip=config["ip"],
        )
        graph.add_edge(
            name, config["switch"], capacity_mbps=1000, base_delay_ms=0.5,
            kind="access", vlan=config["vlan"],
        )

    return graph


ENTERPRISE_HOST_PAIRS = [
    ("h1", "h8"),   # admin -> DNS
    ("h2", "h11"),  # finance -> finance service
    ("h4", "h9"),   # branch 1 -> HTTP
    ("h6", "h8"),   # branch 2 -> DNS
    ("h4", "h6"),   # branch-to-branch permitted traffic scenario
    ("h3", "h12"),  # IT -> management
]
