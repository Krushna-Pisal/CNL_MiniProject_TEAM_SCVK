"""
run_experiment.py
Top-level script: runs the full experiment (ML training + routing
simulation) and exports everything the HTML dashboard needs into
../results/results.json and ../results/topology.png
"""

import json
import os
import argparse
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import networkx as nx

from topology import build_topology
from controller_sim import simulate, select_flow_route
from enterprise_config import HOSTS, VLAN_SEGMENTS, policy_allows
from enterprise_topology import build_enterprise_topology, ENTERPRISE_HOST_PAIRS

OUT_DIR = os.path.join(os.path.dirname(__file__), "..", "results")
os.makedirs(OUT_DIR, exist_ok=True)


def draw_topology(G, path):
    pos = {
        "s1": (0, 2), "s2": (2, 3), "s3": (2, 1), "s4": (4, 3),
        "s5": (4, 1.6), "s6": (4, 0.4), "s7": (6, 2.3), "s8": (6, 1),
        "h1": (-1.5, 2), "h2": (2, 4.3), "h3": (2, -0.3),
        "h4": (4, -0.9), "h5": (7.5, 2.6), "h6": (7.5, 0.6),
    }
    plt.figure(figsize=(9, 5.2))
    switch_nodes = [n for n, d in G.nodes(data=True) if d["kind"] == "switch"]
    host_nodes = [n for n, d in G.nodes(data=True) if d["kind"] == "host"]

    nx.draw_networkx_edges(G, pos, width=1.6, edge_color="#94a3b8")
    nx.draw_networkx_nodes(G, pos, nodelist=switch_nodes, node_color="#2563eb",
                            node_shape="s", node_size=900)
    nx.draw_networkx_nodes(G, pos, nodelist=host_nodes, node_color="#16a34a",
                            node_shape="o", node_size=650)
    nx.draw_networkx_labels(G, pos, font_color="white", font_size=9, font_weight="bold")

    edge_labels = {(u, v): f'{d["capacity_mbps"]}M' for u, v, d in G.edges(data=True) if d["kind"] == "core"}
    nx.draw_networkx_edge_labels(G, pos, edge_labels=edge_labels, font_size=7, font_color="#475569")

    plt.axis("off")
    plt.tight_layout()
    plt.savefig(path, dpi=160, transparent=True)
    plt.close()


def run_baseline():
    G = build_topology()
    draw_topology(G, os.path.join(OUT_DIR, "topology.png"))

    df, clf_metrics, G = simulate(n_intervals=24, flows_per_interval=22, seed=7)

    latency_improvement = (
        (df["avg_latency_static"].mean() - df["avg_latency_adaptive"].mean())
        / df["avg_latency_static"].mean() * 100
    )
    drop_reduction = (
        (df["dropped_static"].sum() - df["dropped_adaptive"].sum())
        / max(1, df["dropped_static"].sum()) * 100
    )
    peak_util_reduction = (
        (df["max_util_static"].mean() - df["max_util_adaptive"].mean())
        / df["max_util_static"].mean() * 100
    )

    payload = {
        "intervals": df["interval"].tolist(),
        "avg_latency_static": df["avg_latency_static"].round(2).tolist(),
        "avg_latency_adaptive": df["avg_latency_adaptive"].round(2).tolist(),
        "max_util_static": df["max_util_static"].round(2).tolist(),
        "max_util_adaptive": df["max_util_adaptive"].round(2).tolist(),
        "dropped_static": df["dropped_static"].tolist(),
        "dropped_adaptive": df["dropped_adaptive"].tolist(),
        "n_flows": df["n_flows"].tolist(),
        "summary": {
            "latency_improvement_pct": round(latency_improvement, 1),
            "drop_reduction_pct": round(drop_reduction, 1),
            "peak_util_reduction_pct": round(peak_util_reduction, 1),
            "classifier_accuracy_pct": round(clf_metrics["accuracy"] * 100, 1),
            "total_static_drops": int(df["dropped_static"].sum()),
            "total_adaptive_drops": int(df["dropped_adaptive"].sum()),
        },
        "classifier": {
            "accuracy": clf_metrics["accuracy"],
            "labels": clf_metrics["labels"],
            "confusion_matrix": clf_metrics["confusion_matrix"],
            "feature_importance": clf_metrics["feature_importance"],
        },
        "topology": {
            "n_switches": sum(1 for _, d in G.nodes(data=True) if d["kind"] == "switch"),
            "n_hosts": sum(1 for _, d in G.nodes(data=True) if d["kind"] == "host"),
            "n_links": G.number_of_edges(),
        },
    }

    with open(os.path.join(OUT_DIR, "results.json"), "w") as f:
        json.dump(payload, f, indent=2)

    print(json.dumps(payload["summary"], indent=2))
    print("Saved results to", OUT_DIR)


def run_enterprise():
    """Run opt-in enterprise workload without touching baseline artifacts."""
    graph = build_enterprise_topology()
    df, clf_metrics, graph = simulate(
        n_intervals=24, flows_per_interval=22, seed=17,
        topology=graph, host_pairs=ENTERPRISE_HOST_PAIRS,
    )
    static_mean = float(df["avg_latency_static"].mean())
    adaptive_mean = float(df["avg_latency_adaptive"].mean())
    static_peak_mean = float(df["max_util_static"].mean())
    adaptive_peak_mean = float(df["max_util_adaptive"].mean())
    summary = {
        "mode": "enterprise_simulation",
        "intervals": int(len(df)),
        "flows_per_interval": int(df["n_flows"].iloc[0]),
        "latency_improvement_pct": round((static_mean - adaptive_mean) / static_mean * 100, 1),
        "peak_util_reduction_pct": round((static_peak_mean - adaptive_peak_mean) / static_peak_mean * 100, 1),
        "static_drops": int(df["dropped_static"].sum()),
        "adaptive_drops": int(df["dropped_adaptive"].sum()),
        "classifier_accuracy_pct": round(clf_metrics["accuracy"] * 100, 1),
    }

    # Repeatable logical failover experiment: choose a known B1/HQ link,
    # verify a route before and after removing it, and report paths rather
    # than inventing wall-clock detection or recovery measurements.
    failed_edge = ("s5", "s7")
    before_path = nx.shortest_path(graph, "h4", "h9", weight="base_delay_ms")
    failed_graph = graph.copy()
    failed_graph.remove_edge(*failed_edge)
    after_path = nx.shortest_path(failed_graph, "h4", "h9", weight="base_delay_ms")
    failover = {
        "mode": "graph_simulation",
        "source": "h4",
        "destination": "h9",
        "failed_link": list(failed_edge),
        "path_before": before_path,
        "path_after": after_path,
        "alternate_path_available": True,
        "alternate_avoids_failed_link": all(
            set(edge) != set(failed_edge) for edge in zip(after_path[:-1], after_path[1:])
        ),
        "detection_time_ms": None,
        "recovery_time_ms": None,
        "packet_loss": None,
        "timing_note": "Logical graph removal only; wall-clock Mininet measurements require the Linux failover script.",
    }

    policy_cases = [
        ("finance_to_finance_service", "h2", "h11", "tcp", 8443, True),
        ("branch_to_http", "h4", "h9", "tcp", 80, True),
        ("branch_to_dns", "h6", "h8", "udp", 53, True),
        ("branch_to_finance_service", "h4", "h11", "tcp", 8443, False),
        ("finance_to_management", "h2", "h12", "tcp", 22, False),
        ("branch_to_branch_icmp", "h4", "h6", "icmp", 0, True),
        ("branch_to_branch_https", "h4", "h6", "tcp", 443, False),
    ]
    policy_results = []
    for name, src, dst, proto, port, expected in policy_cases:
        actual = policy_allows(HOSTS[src], HOSTS[dst], proto, port)
        policy_results.append({"name": name, "source": src, "destination": dst,
                               "protocol": proto, "port": port,
                               "expected_allowed": expected, "allowed": actual,
                               "passed": actual == expected})

    # Routes are calculated here by the Python graph/router code and embedded
    # as read-only choices for the standalone dashboard animation. The browser
    # does not implement a second routing engine.
    priority_by_class = {"voice": 1, "video": 2, "web": 3, "bulk": 4}
    hosts = sorted(HOSTS)
    route_choices = {}
    for src in hosts:
        for dst in hosts:
            if src == dst:
                continue
            for traffic_class, priority in priority_by_class.items():
                key = f"{src}|{dst}|{traffic_class}"
                route_choices[key] = {}
                for mode in ("static", "adaptive"):
                    route_choices[key][mode] = select_flow_route(
                        graph, src, dst, mode, priority=priority)
                    route_choices[key][mode + "_congested"] = select_flow_route(
                        graph, src, dst, mode, priority=priority,
                        link_load_mbps={frozenset(("s5", "s7")): graph["s5"]["s7"]["capacity_mbps"]})
                    route_choices[key][mode + "_failed"] = select_flow_route(
                        graph, src, dst, mode, priority=priority,
                        failed_links=[("s5", "s7")])
    packet_policy = {}
    for src in hosts:
        for dst in hosts:
            for protocol, ports in {"tcp": [0, 21, 22, 53, 80, 443, 8443],
                                    "udp": [0, 53, 5060], "icmp": [0]}.items():
                for port in ports:
                    packet_policy[f"{src}|{dst}|{protocol}|{port}"] = policy_allows(
                        HOSTS[src], HOSTS[dst], protocol, port)

    payload = {
        "summary": summary,
        "intervals": df["interval"].tolist(),
        "avg_latency_static": df["avg_latency_static"].round(2).tolist(),
        "avg_latency_adaptive": df["avg_latency_adaptive"].round(2).tolist(),
        "max_util_static": df["max_util_static"].round(2).tolist(),
        "max_util_adaptive": df["max_util_adaptive"].round(2).tolist(),
        "dropped_static": df["dropped_static"].tolist(),
        "dropped_adaptive": df["dropped_adaptive"].tolist(),
        "n_flows": df["n_flows"].tolist(),
        "classifier": {
            "accuracy": clf_metrics["accuracy"],
            "labels": clf_metrics["labels"],
            "confusion_matrix": clf_metrics["confusion_matrix"],
            "feature_importance": clf_metrics["feature_importance"],
        },
        "topology": {
            "n_switches": sum(d.get("kind") == "switch" for _, d in graph.nodes(data=True)),
            "n_hosts": sum(d.get("kind") == "host" for _, d in graph.nodes(data=True)),
            "n_links": graph.number_of_edges(),
            "sites": ["Headquarters", "Branch Office 1", "Branch Office 2"],
            "vlans": VLAN_SEGMENTS,
            "links": [
                {"a": str(u), "b": str(v), "kind": data.get("kind"),
                 "capacity_mbps": data["capacity_mbps"],
                 "delay_ms": data["base_delay_ms"], "state": "up_in_simulation"}
                for u, v, data in graph.edges(data=True)
            ],
            "nodes": [
                {"id": str(node), "kind": data["kind"],
                 "site": data.get("site", HOSTS.get(node, {}).get("site")),
                 "role": data.get("department", HOSTS.get(node, {}).get("role", "switch")),
                 "ip": HOSTS.get(node, {}).get("ip"),
                 "vlan": HOSTS.get(node, {}).get("vlan"),
                 "switch": HOSTS.get(node, {}).get("switch")}
                for node, data in graph.nodes(data=True)
            ],
        },
        "packet_simulation": {
            "source": "python_graph_router",
            "routes": route_choices,
            "policy_outcomes": packet_policy,
            "classes": list(priority_by_class),
            "failure_scenario": {"link": ["s5", "s7"], "type": "logical_graph_removal"},
            "congestion_scenario": {"link": ["s5", "s7"],
                                    "input": "100% of configured link capacity",
                                    "type": "user-selected simulated load"},
        },
        "health": {
            "source": "python_graph_simulation",
            "controller_status": "simulation_complete_not_live",
            "active_flows_per_interval": int(df["n_flows"].iloc[0]),
            "static_congested_intervals": int((df["max_util_static"] > 100).sum()),
            "adaptive_congested_intervals": int((df["max_util_adaptive"] > 100).sum()),
            "recent_events": [
                {"event": "enterprise_experiment_completed", "intervals": int(len(df))},
                {"event": "logical_link_failure", "link": failover["failed_link"]},
                {"event": "alternate_path_selected", "path": failover["path_after"]},
            ],
        },
        "security": {
            "mode": "policy_unit_simulation",
            "cases": policy_results,
            "passed": sum(case["passed"] for case in policy_results),
            "total": len(policy_results),
            "note": "These are policy logic checks, not live Mininet packet measurements.",
        },
        "failover": failover,
    }

    output = os.path.join(OUT_DIR, "enterprise_results.json")
    with open(output, "w", encoding="utf-8") as result_file:
        json.dump(payload, result_file, indent=2)

    pos = nx.spring_layout(graph, seed=17, weight="capacity_mbps")
    plt.figure(figsize=(12, 7))
    switches = [n for n, d in graph.nodes(data=True) if d["kind"] == "switch"]
    hosts = [n for n, d in graph.nodes(data=True) if d["kind"] == "host"]
    nx.draw_networkx_edges(graph, pos, edge_color="#94a3b8", width=1.3)
    nx.draw_networkx_nodes(graph, pos, nodelist=switches, node_color="#2563eb", node_shape="s", node_size=700)
    nx.draw_networkx_nodes(graph, pos, nodelist=hosts, node_color="#16a34a", node_size=430)
    nx.draw_networkx_labels(graph, pos, font_color="white", font_size=7)
    core_labels = {(u, v): f'{d["capacity_mbps"]}M/{d["base_delay_ms"]}ms'
                   for u, v, d in graph.edges(data=True) if d.get("kind") == "core"}
    nx.draw_networkx_edge_labels(graph, pos, edge_labels=core_labels, font_size=6)
    plt.axis("off")
    plt.tight_layout()
    topology_image = os.path.join(OUT_DIR, "enterprise_topology.png")
    plt.savefig(topology_image, dpi=160, transparent=True)
    plt.close()

    # Embed only the generated enterprise payload. Baseline JSON and the
    # dashboard's original `DATA` object are not replaced.
    dashboard = os.path.join(os.path.dirname(__file__), "..", "index.html")
    with open(dashboard, encoding="utf-8") as dashboard_file:
        html = dashboard_file.read()
    begin_marker, end_marker = "/*__ENTERPRISE_DATA_BEGIN__*/", "/*__ENTERPRISE_DATA_END__*/"
    if begin_marker not in html or end_marker not in html:
        raise RuntimeError("Dashboard enterprise data marker is missing; baseline dashboard was not updated.")
    start = html.index(begin_marker) + len(begin_marker)
    end = html.index(end_marker, start)
    with open(dashboard, "w", encoding="utf-8", newline="") as dashboard_file:
        dashboard_file.write(html[:start] + " " + json.dumps(payload, separators=(",", ":")) + " " + html[end:])

    print(json.dumps(summary, indent=2))
    print("Saved enterprise results to", output)
    print("Saved enterprise topology to", topology_image)


def main():
    parser = argparse.ArgumentParser(description="Run the original or enterprise SDN experiment")
    parser.add_argument("--mode", choices=("baseline", "enterprise"), default="baseline")
    args = parser.parse_args()
    if args.mode == "enterprise":
        run_enterprise()
    else:
        run_baseline()


if __name__ == "__main__":
    main()
