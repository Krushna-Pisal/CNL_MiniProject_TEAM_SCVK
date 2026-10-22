"""
run_experiment.py
Top-level script: runs the full experiment (ML training + routing
simulation) and exports everything the HTML dashboard needs into
../results/results.json and ../results/topology.png
"""

import json
import os
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import networkx as nx

from topology import build_topology
from controller_sim import simulate

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


def main():
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


if __name__ == "__main__":
    main()
