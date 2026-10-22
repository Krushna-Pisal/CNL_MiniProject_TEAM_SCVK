"""
controller_sim.py
Simulates an SDN controller operating over multiple time intervals, routing
flows either:
    (a) STATIC   - classic shortest-path routing, weight = fixed (1/capacity),
                   same as a non-adaptive OSPF-like controller. Never reacts
                   to congestion.
    (b) ADAPTIVE - our AI-driven controller. It uses the CongestionPredictor
                   to forecast each link's utilization for the *next*
                   interval, and the TrafficClassifier's priority output to
                   weight latency-sensitive flows more carefully. Path cost
                   = predicted_utilization based penalty + priority-aware
                   delay term. Recomputes best path per flow, per interval
                   (this is exactly what a Ryu/ONOS app does when it pushes
                   new flow rules after polling switch stats).

For every interval we:
    1. generate new flows
    2. classify them (ML model #1)
    3. route them with both strategies
    4. update link load / utilization for both strategies independently
    5. record latency, packet loss and utilization
    6. feed the interval's utilization history to the CongestionPredictor
       (ML model #2) so it can forecast the *next* interval for adaptive
       routing
"""

import numpy as np
import networkx as nx
import pandas as pd

from topology import build_topology, HOST_PAIRS
from traffic_gen import generate_flows
from ml_models import TrafficClassifier, CongestionPredictor


def path_delay_ms(G, path, extra_penalty=0.0):
    delay = 0.0
    for u, v in zip(path[:-1], path[1:]):
        delay += G[u][v]["base_delay_ms"]
    return delay + extra_penalty


def simulate(n_intervals=20, flows_per_interval=14, seed=7):
    rng = np.random.default_rng(seed)
    G = build_topology()
    edges = list(G.edges())

    # independent utilization state per strategy (bytes accumulated -> reset each interval)
    util_static = {e: [] for e in edges}
    util_adaptive = {e: [] for e in edges}

    clf = TrafficClassifier()
    # bootstrap-train the classifier once on a large synthetic batch (offline training,
    # like you would do before deploying the model to the controller)
    bootstrap_df = generate_flows(1500, HOST_PAIRS, seed=1)
    clf_metrics = clf.fit(bootstrap_df)

    congestion_predictor = CongestionPredictor(window=4)
    # link utilization history, one series per edge, used to train + forecast
    link_history = {e: [] for e in edges}

    interval_records = []

    for t in range(n_intervals):
        flows = generate_flows(flows_per_interval, HOST_PAIRS, seed=100 + t)
        flows["pred_class"] = clf.predict(flows)
        # process latency-sensitive (voice/video) flows first, like a
        # priority queue an SDN controller would apply
        flows = flows.sort_values("priority").reset_index(drop=True)

        cap = {e: G[e[0]][e[1]]["capacity_mbps"] for e in edges}

        def norm_edge(u, v, table):
            return (u, v) if (u, v) in table else (v, u)

        # --- forecast BASELINE next-interval utilization per edge (carried
        # over congestion trend), used only by the adaptive strategy as a
        # warm-start prior before any flow this interval has been placed ---
        forecast = {}
        for e in edges:
            hist = link_history[e]
            if len(hist) >= congestion_predictor.window + 3:
                arr = np.array(hist)
                congestion_predictor.fit(arr)
                forecast[e] = max(0.0, congestion_predictor.predict_next(arr[-congestion_predictor.window:]))
            else:
                forecast[e] = 0.0

        # reset per-interval load counters (both start empty - the difference
        # is *how* each strategy chooses paths as load accumulates, and the
        # adaptive strategy additionally nudges its choice using the ML
        # congestion forecast as a proactive prior)
        load_static = {e: 0.0 for e in edges}
        load_adaptive = {e: 0.0 for e in edges}

        total_latency_static, total_latency_adaptive = [], []
        dropped_static, dropped_adaptive = 0, 0

        # ---------------- STATIC strategy ----------------
        # Classic non-adaptive routing (like static OSPF cost = link delay):
        # cost never changes with traffic already placed, so many flows
        # pile onto the same "shortest" path even after it gets congested.
        def static_weight(u, v, d):
            return d["base_delay_ms"]

        for _, flow in flows.iterrows():
            src, dst, demand = flow["src"], flow["dst"], flow["demand_mbps"]
            path_s = nx.shortest_path(G, src, dst, weight=static_weight)
            for u, v in zip(path_s[:-1], path_s[1:]):
                e = norm_edge(u, v, load_static)
                load_static[e] += demand
            util_ratio_s = max(
                load_static[norm_edge(u, v, load_static)] / cap[norm_edge(u, v, cap)]
                for u, v in zip(path_s[:-1], path_s[1:])
            )
            congestion_penalty_s = max(0, util_ratio_s - 1) * 150  # queueing/drop penalty once over capacity
            lat_s = path_delay_ms(G, path_s, congestion_penalty_s)
            if util_ratio_s > 1.0:
                dropped_static += 1
            total_latency_static.append(lat_s)

        # ---------------- ADAPTIVE (AI-driven SDN) strategy ----------------
        # Controller has a real-time global view: path cost reacts to the
        # load *already placed this interval* (updated after every flow,
        # exactly like a controller re-polling switch stats) plus the ML
        # congestion forecast, plus priority-aware conservativeness for
        # delay-sensitive classes predicted by the traffic classifier.
        for _, flow in flows.iterrows():
            src, dst, demand, priority = flow["src"], flow["dst"], flow["demand_mbps"], flow["priority"]

            def adaptive_weight(u, v, d):
                e = norm_edge(u, v, load_adaptive)
                util_ratio = load_adaptive[e] / cap[e]                    # reactive: load placed so far this interval
                predicted_ratio = forecast[norm_edge(u, v, forecast)] / 100.0  # proactive: ML trend forecast
                base = d["base_delay_ms"]
                congestion_term = (max(0.0, util_ratio) ** 3) * 35
                forecast_term = (max(0.0, predicted_ratio) ** 3) * 12
                priority_factor = {1: 1.6, 2: 1.3, 3: 1.0, 4: 0.7}[priority]
                return base + (congestion_term + forecast_term) * priority_factor

            path_a = nx.shortest_path(G, src, dst, weight=adaptive_weight)
            for u, v in zip(path_a[:-1], path_a[1:]):
                e = norm_edge(u, v, load_adaptive)
                load_adaptive[e] += demand
            util_ratio_a = max(
                load_adaptive[norm_edge(u, v, load_adaptive)] / cap[norm_edge(u, v, cap)]
                for u, v in zip(path_a[:-1], path_a[1:])
            )
            congestion_penalty_a = max(0, util_ratio_a - 1) * 150
            lat_a = path_delay_ms(G, path_a, congestion_penalty_a)
            if util_ratio_a > 1.0:
                dropped_adaptive += 1
            total_latency_adaptive.append(lat_a)

        # record per-edge utilization % for this interval (both strategies), update history
        for e in edges:
            u_s = 100.0 * load_static[e] / cap[e]
            u_a = 100.0 * load_adaptive[e] / cap[e]
            util_static[e].append(u_s)
            util_adaptive[e].append(u_a)
            # adaptive strategy's *actual realised* utilization feeds next forecast
            link_history[e].append(u_a)

        interval_records.append(dict(
            interval=t,
            avg_latency_static=float(np.mean(total_latency_static)),
            avg_latency_adaptive=float(np.mean(total_latency_adaptive)),
            max_util_static=float(max(100.0 * load_static[e] / cap[e] for e in edges)),
            max_util_adaptive=float(max(100.0 * load_adaptive[e] / cap[e] for e in edges)),
            dropped_static=dropped_static,
            dropped_adaptive=dropped_adaptive,
            n_flows=len(flows),
        ))

    results_df = pd.DataFrame(interval_records)
    return results_df, clf_metrics, G


if __name__ == "__main__":
    df, metrics, G = simulate()
    print(df)
    print("Classifier accuracy:", metrics["accuracy"])
