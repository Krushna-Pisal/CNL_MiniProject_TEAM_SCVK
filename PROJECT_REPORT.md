# CNL Mini Project Team SCVK

## AI-Driven Adaptive Network Traffic Management Using SDN and Machine Learning

**Project report**  
**Course:** Computer Networks  
**Team:** SCVK  
**Institution:** [Enter institution name]  
**Submitted by:** [Enter student names and roll numbers]  
**Submitted to:** [Enter instructor name]  
**Academic year:** [Enter academic year]

> Replace the bracketed fields on the cover page with the details required by your department. This report describes the code and saved results in this repository. The numerical comparison is from the Python simulation; the Mininet section describes a separate implementation and its sample run logs.

---

## Abstract

Conventional shortest-path routing generally selects paths using relatively fixed metrics such as propagation delay. When traffic changes, a fixed route may continue using a busy link even when an alternate path is available. This project studies whether a Software-Defined Networking (SDN) controller can improve routing decisions by considering traffic class, current link utilization, and predicted near-term utilization.

The project has two implementations. The Python simulation models an eight-switch, six-host network and compares fixed delay-based routing with an adaptive controller over 24 intervals, using the same generated traffic for both strategies. A Random Forest classifier labels synthetic flows as voice, video, web, or bulk; a Random Forest regressor forecasts link utilization from recent history. In the saved experiment, the classifier achieved 99.7% held-out accuracy. Adaptive routing reduced mean interval flow latency by 15.2%, reduced the mean of per-interval peak link utilization by 38.8%, and recorded zero simulated drops compared with 23 for static routing. A second implementation uses Mininet, Open vSwitch, and OpenFlow 1.3 to demonstrate routing over a small emulated network. The report distinguishes these two forms of evidence and discusses the synthetic-data and implementation limits.

**Keywords:** Software-Defined Networking, SDN, adaptive routing, Random Forest, traffic classification, congestion prediction, Mininet, OpenFlow.

## 1. Introduction

Networks carry applications with different requirements. Voice traffic is sensitive to delay, while bulk transfers can generally tolerate a longer route. A path that is shortest by propagation delay may become overloaded when many flows share it. A controller that can observe the network as a whole can choose among alternate paths and take traffic priorities into account.

SDN separates the control logic that decides how traffic should be forwarded from the switches that forward packets. A software controller can maintain a topology view, collect statistics, compute routes, and install forwarding rules. Machine learning can contribute by classifying flows and estimating future link load from recent observations.

This project implements and compares two routing approaches: a fixed delay-based baseline and an adaptive approach that adds load and forecast penalties to route cost. A synthetic simulation provides repeatable comparative metrics. A separate Mininet implementation illustrates the controller and forwarding logic with virtual switches and links.

## 2. Problem statement

Fixed shortest-path routing does not respond to the load created by earlier flows. If the selected path becomes congested, later flows may continue to use it, causing higher modeled delay and drops even though the topology contains alternate routes. The project addresses the following question:

**Can an SDN controller that considers traffic priority, current load, and a forecast of link utilization route new flows with lower modeled congestion and latency than a fixed delay-based controller on the same traffic?**

## 3. Objectives

1. Model a small network with redundant paths and heterogeneous link capacities and delays.
2. Generate reproducible synthetic traffic representing four application classes.
3. Train and evaluate a flow classifier using observable flow features.
4. Forecast next-interval link utilization from a short utilization history.
5. Compare delay-only and adaptive route selection on identical per-interval traffic.
6. Export metrics and a topology diagram for a browser dashboard.
7. Provide a Mininet/Open vSwitch implementation that demonstrates OpenFlow routing and congestion-aware path selection.

## 4. Scope and system overview

The repository contains two related implementations. `src/` is the quantitative simulation used to create `results/results.json`. It uses a graph model and synthetic flows rather than live packets. `mininet_sdn/` is an emulated SDN implementation using Mininet, Open vSwitch, and OS-Ken (Ryu-compatible APIs). It collects switch statistics and installs OpenFlow rules. The Mininet sample logs are example captured output; the headline 15.2%, 38.8%, and 99.7% figures come from the Python simulation, not from the Mininet demo.

### 4.1 High-level data flow

```text
Synthetic flow features ──> Random Forest classifier ──> traffic class / priority ─┐
                                                                                   ├─> adaptive path cost
Per-link utilization history ──> Random Forest regressor ──> next-step forecast ───┘
                                                                                         │
Topology + link delay/capacity ──────────────────────────────────────────────────────────┤
                                                                                         v
                                                            weighted shortest path (Dijkstra)
                                                                                         │
                                                                                         v
                                                          simulated route / OpenFlow rules
```

## 5. Network topology and traffic model

### 5.1 Topology

The modeled graph contains 8 switches (`s1`–`s8`), 6 hosts (`h1`–`h6`), and 18 links. The switch core is a partial mesh with alternate paths; each host attaches to one edge switch. Core capacities range from 60 to 100 Mbps, and core propagation delays range from 1 to 4 ms. Host access links have 1000 Mbps capacity and 0.5 ms delay. The topology is defined in `src/topology.py` and visualized in `results/topology.png`.

Core links are: s1–s2, s1–s3, s2–s4, s3–s4, s2–s5, s3–s6, s4–s7, s5–s7, s6–s7, s5–s8, s6–s8, and s7–s8. Hosts h1 through h6 attach respectively to s1, s2, s3, s6, s7, and s8. Six endpoint pairs are used as candidate source/destination pairs by the simulator.

### 5.2 Synthetic traffic

The generator creates flows from four classes: voice, video, web, and bulk. The class mixture probabilities are 20%, 25%, 35%, and 20%, respectively. Flow features include average packet size, average inter-arrival time, duration, offered demand, packet count, source, and destination. Class profiles are statistical distributions encoded in `src/traffic_gen.py`; they are synthetic labels and should not be interpreted as measurements from a real network trace.

The simulation uses a fixed seed for repeatability, runs 24 intervals, and generates 22 flows per interval, for 528 generated flows. Both routing strategies receive the same generated flows in each interval. The classifier is bootstrapped on 1,500 generated examples and evaluated using a stratified 75/25 train/test split.

## 6. Machine-learning methods

### 6.1 Traffic classification

The `TrafficClassifier` is a scikit-learn `RandomForestClassifier` with 150 trees and maximum depth 8. Its input features are:

| Feature | Description |
|---|---|
| `avg_pkt_size` | Mean packet size in bytes |
| `avg_iat_ms` | Mean inter-arrival time in milliseconds |
| `duration_s` | Flow duration in seconds |
| `demand_mbps` | Estimated flow demand in megabits per second |
| `n_packets` | Number of packets in the generated flow |

The model predicts one of four labels: bulk, video, voice, or web. In the saved test split it correctly classified 374 of 375 examples (99.73%). The only error was one video flow classified as web. Since train and test records come from the same synthetic generator, this result measures performance on that generator's distributions and does not establish accuracy on external traffic.

### 6.2 Congestion prediction

The `CongestionPredictor` is a `RandomForestRegressor` with 120 trees and maximum depth 6. It converts a utilization series into lagged examples: the preceding four utilization observations are used to predict the next observation. The regressor is refit as history accumulates, and the adaptive simulator uses its next-step output as a forecast penalty. Early in the run, when insufficient link history is available, the forecast is initialized to zero.

The code calculates a holdout mean absolute error during fitting, but the saved results file does not include aggregate predictor MAE. Consequently, this report does not claim a numerical forecasting accuracy.

### 6.3 Feature importance

The classifier's saved Random Forest feature importance values are:

| Feature | Importance |
|---|---:|
| Flow duration | 0.364 |
| Average packet size | 0.231 |
| Offered demand | 0.196 |
| Packet count | 0.126 |
| Average inter-arrival time | 0.084 |

These values describe how the fitted forest used features for splits in this synthetic experiment. They are not causal effects or proof that the same ranking applies to operational network traces.

## 7. Routing design

### 7.1 Static baseline

The static strategy chooses a path with Dijkstra's algorithm using only the fixed propagation delay on each link. It does not change link weights as flows are placed. The simulator accumulates each selected flow's demand on every link along its path. If the maximum utilization ratio of the path exceeds 1, the flow is counted as dropped and a queueing penalty is added to modeled latency.

### 7.2 Adaptive strategy

Flows are processed in priority order (voice first). For each candidate link, the adaptive strategy combines base delay, utilization caused by already placed flows in the current interval, and the predicted utilization for the next interval. The simulator's cost is:

```text
cost = base_delay
     + 35 × current_utilization_ratio³ × priority_factor
     + 12 × forecast_utilization_ratio³ × priority_factor
```

The priority factors are 1.6 for voice, 1.3 for video, 1.0 for web, and 0.7 for bulk. The congestion penalties grow nonlinearly with utilization, making heavily loaded links less attractive. Dijkstra's algorithm then chooses the path with the lowest total edge cost. The same post-routing overload rule is used to count drops for both strategies.

### 7.3 Distinction from the Mininet controller

In the Mininet implementation, OS-Ken polls real OpenFlow port counters and predicts link utilization. It computes paths for new flows and sends per-hop OpenFlow flow-mod messages. Initial priority assignment at first packet is port-based (for example, UDP 5060 maps to voice); the trained classifier subsequently analyzes live flow statistics and logs classifications. The documentation identifies using that ML output to migrate already-established flows as future work. Thus, the live implementation should not be described as using the ML classifier to assign the first-packet route class.

## 8. Implementation details

### 8.1 Simulation components

| File | Responsibility |
|---|---|
| `src/topology.py` | Constructs graph, link properties, and host pairs |
| `src/traffic_gen.py` | Generates labeled synthetic flow records |
| `src/ml_models.py` | Defines classifier and utilization forecaster |
| `src/controller_sim.py` | Runs static/adaptive routing and records interval metrics |
| `src/run_experiment.py` | Executes the experiment and writes JSON and topology image |
| `index.html` | Self-contained dashboard for presenting the project |

The main experiment command is `python src/run_experiment.py` from the repository root. Dependencies are listed in `requirements.txt`. The run writes `results/results.json` and `results/topology.png`.

### 8.2 Mininet components

The `mininet_sdn/` directory contains the Mininet topology, OS-Ken controllers, shared topology helpers, traffic-class mapping, model training script, and shell demo. It requires a Linux environment with Mininet, Open vSwitch, `iproute2`, `iperf`, and Python dependencies. The documented demo runs static and adaptive modes against a bulk transfer and then a voice flow. The included sample logs show the static route taking the congested s2–s4 path, while the adaptive controller routes the new voice flow via s2–s5–s7.

## 9. Experimental methodology

1. Build the graph and create 1,500 synthetic flows for classifier training and held-out evaluation.
2. For each of 24 intervals, generate 22 flows using a deterministic interval seed.
3. Classify flows and process them in ascending priority number.
4. Route the same per-interval flow set using static and adaptive strategies with separate load state.
5. Accumulate link demands, compute interval latency/utilization/drop metrics, and append utilization history for later forecasts.
6. Average the recorded interval metrics and export results.

The comparison is controlled in the sense that each routing strategy sees the same generated demand per interval. It is a software simulation, not a randomized real-world trial. It does not model all queueing, transport-layer behavior, packet-level events, controller overhead, or realistic variability in link measurements.

## 10. Results

### 10.1 Summary

| Metric | Static routing | Adaptive routing | Change |
|---|---:|---:|---:|
| Held-out traffic-classifier accuracy | Not applicable to routing baseline | 99.7% | Classifier score |
| Mean flow latency across interval averages | Baseline | 15.2% lower | 15.2% reduction |
| Mean per-interval maximum link utilization | Baseline | 38.8% lower | 38.8% reduction |
| Simulated dropped flows over 24 intervals | 23 | 0 | 100% fewer in this run |

The 38.8% figure is computed by comparing the mean of the 24 `max_util_*` values. It is not the single highest value observed across all links and intervals. The latency comparison similarly uses the mean of interval-average latencies. These definitions follow `src/run_experiment.py`.

### 10.2 Classifier confusion matrix

Rows are actual labels and columns are predicted labels in the saved label order `[bulk, video, voice, web]`.

| Actual  Predicted | Bulk | Video | Voice | Web |
|---|---:|---:|---:|---:|
| Bulk | 77 | 0 | 0 | 0 |
| Video | 0 | 91 | 0 | 1 |
| Voice | 0 | 0 | 72 | 0 |
| Web | 0 | 0 | 0 | 134 |

### 10.3 Interpretation

The simulation indicates that load-aware routing can distribute flows across alternate paths and avoid some overloaded links. In this particular deterministic workload, the adaptive controller recorded no drops, while delay-only routing overloaded paths in several intervals. Adaptive latency is not lower in every individual interval; the result is an aggregate improvement over the complete run. The result supports the project hypothesis for this modeled topology and workload, but should not be generalized to all traffic patterns or real networks without additional testing.

## 11. Mininet demonstration evidence

The repository includes captured logs for a separate live emulation scenario. A 60 Mbps bulk `iperf` transfer is directed across a route containing s2–s4. A subsequent voice flow from h2 to h5 is routed by the static controller through `[2, 4, 7]`, which includes the congested link. In the sample adaptive log, the voice flow takes `[2, 5, 7]`, avoiding s2–s4. The adaptive controller also polls real switch statistics and runs the trained classifier against flow statistics. These logs are evidence of the captured demo scenario, not additional rows in the simulation's 24-interval metric table.

## 12. Limitations and threats to validity

1. **Synthetic traffic:** class labels and feature distributions are generated from hand-coded profiles. Real traffic may overlap more and include encrypted, mixed, or changing application behavior.
2. **Classifier evaluation:** training and test examples are drawn from the same generator. The reported accuracy does not measure generalization to independent datasets or live networks.
3. **Forecast evaluation:** aggregate forecasting error is not exported with the results, so the report cannot quantify forecast quality.
4. **Simplified performance model:** the simulation models overload penalties and drops with simplified rules rather than packet-level queueing and transport dynamics.
5. **Single seed/configuration:** the headline comparison represents one configured run. Multiple seeds, traffic intensities, topologies, and confidence intervals would make the evaluation stronger.
6. **Controller overhead:** route computation cost, polling overhead, rule-install latency, and route oscillation are not represented fully in the simulation.
7. **Mininet topology discovery:** the topology is hardcoded rather than discovered dynamically through LLDP.
8. **Mininet first-packet classification:** the initial priority uses port heuristics. The trained classifier processes live flow statistics afterward and logs its classification; automatic mid-flow migration based on that classifier output is not implemented.
9. **Environment dependence:** Mininet/OVS execution requires suitable Linux support and privileges. Userspace OVS is slower than the kernel datapath, and link shaping depends on kernel `tc`/`netem` support.

## 13. Future work

- Evaluate on public or collected flow datasets and test across train/test splits separated by time or capture source.
- Run multiple seeds and report confidence intervals, per-class precision/recall/F1, and forecast MAE.
- Add baselines such as equal-cost multipath, shortest-path by capacity, and reactive load-aware routing without forecasting.
- Implement LLDP-based topology discovery and robust handling of link/switch failures.
- Use calibrated controller polling, EWMA or temporal forecasting alternatives, and safeguards against route oscillation.
- Use ML classification output to trigger carefully controlled flow migration where supported.
- Include packet-level queueing, jitter, loss, and throughput measurements in the evaluation.
- Package the Mininet setup as a reproducible VM/container and automate environment checks.

## 14. Conclusion

This project implements an SDN traffic-management design that combines a Random Forest traffic classifier, a Random Forest utilization forecaster, and weighted shortest-path routing. In the saved Python experiment, adaptive routing improved aggregate latency and utilization measures and eliminated modeled drops for the tested synthetic workload. The Mininet implementation complements this comparison with an OpenFlow-based demonstration that observes switch statistics and can route a new voice flow around a congested path. The results are promising within the project's scope, while synthetic traffic, simplified simulation assumptions, and limited live-controller behavior mean further evaluation is needed before claiming production performance.

## 15. Reproduction instructions

### Python simulation (Windows, Linux, or macOS)

From the repository root:

```bash
python -m pip install -r requirements.txt
python src/run_experiment.py
```

Open `index.html` in a browser to view the dashboard. The output metrics are in `results/results.json` and the generated topology diagram is `results/topology.png`.

### Mininet demo (Ubuntu/Debian)

Read `mininet_sdn/README_MININET.md` first. The documented setup requires system packages including Mininet and Open vSwitch and must be run with the required privileges. In `mininet_sdn/`, install its Python requirements, train the model with `python3 train_models.py`, then use `sudo ./run_demo.sh static` or `sudo ./run_demo.sh adaptive`. The sample logs are available under `mininet_sdn/sample_run_logs/` if a live demo environment is unavailable.

## 16. Viva questions and concise answers

**1. What is SDN?**  
SDN separates network control decisions from packet forwarding and exposes programmable control through a controller. This project uses a centralized controller model to compute paths and install forwarding rules.

**2. Why use machine learning here?**  
The classifier estimates the application class from flow features, and the regressor estimates near-term link utilization. Those outputs inform priority-sensitive path selection.

**3. Why two models?**  
Traffic classification and time-series utilization prediction are different tasks with different inputs and outputs, so separate models make the pipeline easier to evaluate and replace.

**4. Why Random Forest?**  
It is a practical ensemble for tabular features, can model nonlinear feature relationships, and provides feature-importance estimates. This project uses it as a simple baseline rather than claiming it is universally optimal.

**5. What is the difference between static and adaptive routing here?**  
Static routing minimizes fixed link delay. Adaptive routing adds current and predicted utilization penalties and adjusts the cost according to traffic priority.

**6. How does the congestion predictor work?**  
It forms training examples from sliding windows of four past utilization measurements and predicts the next value with a Random Forest regressor.

**7. What does 99.7% accuracy mean?**  
It is the classifier's accuracy on a held-out 25% split of 1,500 synthetic examples generated by the project's own traffic model. It is not a real-world accuracy guarantee.

**8. What does the 38.8% utilization reduction mean?**  
It is the reduction in the mean of each interval's maximum link utilization, comparing the two strategies over 24 intervals.

**9. Is the Mininet implementation fully ML-driven at flow setup?**  
No. Initial priority is assigned using transport-port heuristics. The trained classifier later processes live flow statistics; using its output to migrate existing flows is future work.

**10. What are the key limitations?**  
Synthetic traffic, a simplified simulation, one saved seed/configuration, missing aggregate forecast error in the exported report, and hardcoded Mininet topology are the main limitations.

**11. How could the project be extended?**  
Use real or public traffic traces, evaluate multiple seeds, report uncertainty and per-class metrics, add more routing baselines, discover topology dynamically, and evaluate packet-level performance.

## 17. Project references

These references identify the implementation artifacts used to prepare this report:

1. `src/topology.py` — simulated network graph and host pairs.
2. `src/traffic_gen.py` — synthetic class profiles and flow generation.
3. `src/ml_models.py` — classifier and congestion-prediction model definitions.
4. `src/controller_sim.py` — routing strategies and interval simulation.
5. `src/run_experiment.py` — experiment settings and summary metric calculations.
6. `results/results.json` — saved metrics, confusion matrix, and feature importance.
7. `mininet_sdn/README_MININET.md` — Mininet setup, demo procedure, and limitations.
8. `mininet_sdn/controller_adaptive.py`, `mininet_sdn/controller_static.py` — OS-Ken controller implementations.
9. `mininet_sdn/sample_run_logs/` — captured output from the separate Mininet demonstration.
