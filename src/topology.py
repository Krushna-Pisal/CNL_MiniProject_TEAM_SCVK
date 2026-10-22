"""
topology.py
Defines the simulated SDN network topology.

We model a small enterprise/campus network:
    - 8 OpenFlow switches (s1..s8) forming a partial mesh (multiple paths exist
      between most switch pairs, which is what makes adaptive routing useful)
    - 6 hosts (h1..h6) attached to edge switches
    - Every link has a capacity (Mbps) and a base propagation delay (ms)

This is deliberately similar to a topology you would build in Mininet with
`addLink(s1, s2, bw=100, delay='2ms')`, so the same graph could later be
dropped into a real Mininet + Ryu/POX setup with minimal changes.
"""

import networkx as nx


def build_topology() -> nx.Graph:
    G = nx.Graph()

    switches = [f"s{i}" for i in range(1, 9)]
    hosts = [f"h{i}" for i in range(1, 7)]

    G.add_nodes_from(switches, kind="switch")
    G.add_nodes_from(hosts, kind="host")

    # Core switch mesh (partial mesh -> redundant paths between s1 and s8)
    core_links = [
        ("s1", "s2", 100, 2),
        ("s1", "s3", 100, 3),
        ("s2", "s4", 80, 2),
        ("s3", "s4", 60, 2),
        ("s2", "s5", 60, 4),
        ("s3", "s6", 80, 3),
        ("s4", "s7", 100, 2),
        ("s5", "s7", 60, 2),
        ("s6", "s7", 60, 2),
        ("s5", "s8", 80, 3),
        ("s6", "s8", 100, 2),
        ("s7", "s8", 100, 1),
    ]
    for u, v, bw, delay in core_links:
        G.add_edge(u, v, capacity_mbps=bw, base_delay_ms=delay, kind="core")

    # Edge (access) links connecting hosts to switches
    edge_links = [
        ("h1", "s1", 1000, 0.5),
        ("h2", "s2", 1000, 0.5),
        ("h3", "s3", 1000, 0.5),
        ("h4", "s6", 1000, 0.5),
        ("h5", "s7", 1000, 0.5),
        ("h6", "s8", 1000, 0.5),
    ]
    for u, v, bw, delay in edge_links:
        G.add_edge(u, v, capacity_mbps=bw, base_delay_ms=delay, kind="edge")

    return G


HOST_PAIRS = [
    ("h1", "h6"),
    ("h2", "h5"),
    ("h3", "h4"),
    ("h1", "h5"),
    ("h2", "h6"),
    ("h4", "h5"),
]

if __name__ == "__main__":
    g = build_topology()
    print(f"Nodes: {g.number_of_nodes()}, Edges: {g.number_of_edges()}")
