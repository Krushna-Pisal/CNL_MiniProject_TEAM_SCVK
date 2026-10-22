# CNL Mini Project Team SCVK

## AI-Driven Adaptive Network Traffic Management using SDN and Machine Learning

A computer-networks mini project that simulates a **Software-Defined Network (SDN)
controller** which uses **machine learning** to classify traffic and predict
congestion, then reroutes flows adaptively — and compares it against a
traditional **static, non-adaptive** routing scheme on the same topology and
the same traffic.

Open **`index.html`** in any browser — it's a self-contained dashboard (no
server needed) that presents the whole project to your teacher: architecture,
topology, ML model performance, and the static-vs-adaptive results, all
generated from the actual simulation run in `src/`.

---

## 1. Problem statement

Traditional networks (OSPF/static routing) pick a path based on fixed link
costs (like hop count or delay) and **never change it based on current
traffic**. If a "shortest" path gets congested, every new flow still piles
onto it — causing high latency and packet loss — while a different, slightly
longer path sits idle.

**Idea:** give the network's controller a global view (this is exactly what
SDN provides) plus a machine-learning brain that can (a) tell what *kind* of
traffic a flow is, and (b) forecast which links are *about to* get congested.
Use both to pick better paths in real time.

## 2. Architecture

```
 Flow stats  ─▶ [1] Traffic Classifier (Random Forest)
 (from switches)      classifies: voice / video / web / bulk
                              │
                              ▼
 Link history ─▶ [2] Congestion Predictor (RF Regressor)
                      forecasts next-interval utilization per link
                              │
                              ▼
                 [3] SDN Controller (Dijkstra, re-weighted)
                      path cost = base delay
                               + (current load)^3  x priority factor
                               + (forecast load)^3 x priority factor
                              │
                              ▼
                 [4] Flow rules pushed to switches (simulated)
```

This mirrors a real deployment: a **Ryu** or **ONOS** controller app would
poll OpenFlow switch statistics, run the same two ML models, and call
`nx.shortest_path` (or an equivalent path computation) with adaptive weights
before pushing flow-mod messages to switches. The topology in `topology.py`
is written the same way you'd declare it in **Mininet** (`addLink(s1, s2,
bw=100, delay='2ms')`), so this simulation can be ported to a real Mininet +
Ryu setup with minimal changes if you want to extend the project.

## 3. What's simulated

- **Topology** (`src/topology.py`): 8 OpenFlow switches in a partial mesh (so
  redundant paths genuinely exist between most switch pairs) + 6 hosts, each
  link with its own capacity (Mbps) and propagation delay.
- **Traffic generator** (`src/traffic_gen.py`): synthetic flows from 4
  application classes (voice, video, web, bulk), each with realistic packet
  size / inter-arrival-time / duration / demand distributions — similar in
  spirit to real traffic-classification datasets.
- **ML models** (`src/ml_models.py`):
  - `TrafficClassifier` — Random Forest, trained on 1500 synthetic flows,
    ~99–100% held-out accuracy (the classes are statistically well
    separated, similar to real QoS classification papers).
  - `CongestionPredictor` — Random Forest Regressor on lag features,
    forecasts a link's utilization one interval ahead.
- **Controller simulation** (`src/controller_sim.py`): runs 24 controller
  intervals. In every interval it generates flows, classifies them, and
  routes them **twice** — once with static shortest-path routing, once with
  the AI-adaptive controller — so both strategies see *identical* traffic and
  only the routing decision differs.
- **Experiment driver** (`src/run_experiment.py`): runs everything, saves
  `results/results.json` (all the numbers behind the dashboard) and
  `results/topology.png` (the topology diagram).

## 4. How to run it yourself

```bash
pip install -r requirements.txt
cd src
python3 run_experiment.py
```

This regenerates `results/results.json` and `results/topology.png`. To
rebuild `index.html` from those results (optional — a copy is already
included), see the inline comments in `run_experiment.py`; the dashboard
simply embeds that JSON and image.

## 5. Key results (from the included run)

| Metric | Static routing | AI-Adaptive routing |
|---|---|---|
| Traffic classification accuracy | — | ~99.7% |
| Average flow latency | baseline | ~15% lower |
| Peak link utilization | baseline | ~39% lower |
| Congested / dropped flows | 23 | 0 |

The adaptive controller trades a small amount of routing simplicity for a
large reduction in congestion and drops — because it can see current load
*and* forecast future load, while static routing is blind to both.

## 6. Viva / demo talking points

- **Why SDN, specifically?** Static/distributed protocols like OSPF can't
  react to real-time traffic because no single node has a global view. SDN's
  centralized controller is what makes ML-driven, whole-network optimization
  possible in the first place.
- **Why two ML models and not one?** Classification (what *kind* of traffic)
  and forecasting (what will the *network* look like next) are different
  problems — one is about the flow, the other is about the link. Keeping
  them separate also means either could be swapped for a different model
  (e.g. an LSTM for the time-series part) without touching the other.
- **Why Random Forest?** Good accuracy on tabular, low-dimensional flow
  features, fast to train/infer (matters for a controller making real-time
  decisions), and gives interpretable feature importances — shown in the
  dashboard.
- **What would change for a real deployment?** Replace `topology.py`'s graph
  with a live OpenFlow topology discovery module, replace `traffic_gen.py`
  with real sFlow/NetFlow/OpenFlow stats polling, and replace the simulated
  "push flow rules" step with actual `OFPFlowMod` messages via Ryu/ONOS.

## 7. Project structure

```
├── index.html               ← open this to present the project
├── requirements.txt
├── src/
│   ├── topology.py           network topology (Mininet-style)
│   ├── traffic_gen.py        synthetic flow/traffic generator
│   ├── ml_models.py          traffic classifier + congestion predictor
│   ├── controller_sim.py     static vs adaptive routing simulation
│   ├── run_experiment.py     runs everything, exports results
│   └── template.html         dashboard template (results get injected here)
├── results/
│   ├── results.json          all metrics behind the dashboard
│   └── topology.png          rendered topology diagram
└── mininet_sdn/               ← a REAL Mininet + OVS + OpenFlow deployment
    ├── README_MININET.md      setup + how to run it on your own machine
    ├── network_topo.py        builds the actual Mininet topology
    ├── controller_static.py   real baseline SDN controller (non-adaptive)
    ├── controller_adaptive.py real AI-driven SDN controller
    ├── run_demo.sh            one-command demo (static or adaptive)
    └── sample_run_logs/       real captured output, in case you can't run it live
```

## 8. Two ways to explore this project

This project ships in two layers, and it's worth being clear about which is
which when you present it:

- **`src/` — a fast, large-scale simulation.** Pure Python (networkx +
  scikit-learn), no real network stack. Lets you sweep 24 controller
  intervals and dozens of flows in seconds, which is what the dashboard's
  quantitative comparison (`index.html`) is built from.
- **`mininet_sdn/` — a real SDN deployment.** Actual Mininet switches, real
  Open vSwitch, a real OpenFlow controller (`os-ken`) making live routing
  decisions from real port/flow statistics. Slower to run and smaller in
  scope (a handful of flows, not 24 intervals), but it's the real thing —
  see `mininet_sdn/README_MININET.md` for a captured example where the
  AI-driven controller detects real congestion on a live link and reroutes
  a new flow around it while the baseline controller doesn't.

The simulation provides the quantitative comparison; the Mininet sample
logs provide a separate OpenFlow demonstration that should be rerun on a
supported Linux host to validate the current environment and controller.

## 9. Enterprise multi-branch extension

The opt-in enterprise mode extends the same eight switches rather than
changing the original run. It models Headquarters (s1-s4), Branch Office 1
(s5, s7), Branch Office 2 (s6, s8), 14 department/client/service endpoints,
and three additional redundant core links. `src/enterprise_topology.py`
is separate from `src/topology.py`, so the original six-host simulation is
unchanged. The enterprise simulator writes `results/enterprise_results.json`
and `results/enterprise_topology.png`; it does not overwrite the baseline
results. Running it embeds that generated dataset in the self-contained
`index.html` enterprise section.

### VLAN and subnet plan

| VLAN | Segment | Subnet / gateway | Example endpoints |
|---:|---|---|---|
| 10 | Administration | 10.10.10.0/24 · .1 | h1 |
| 20 | Finance | 10.10.20.0/24 · .1 | h2 |
| 30 | IT | 10.10.30.0/24 · .1 | h3 |
| 40 | Branch 1 users | 10.10.40.0/24 · .1 | h4, h5, h13 |
| 41 | Branch 2 users | 10.10.41.0/24 · .1 | h6, h7, h14 |
| 50 | Shared service endpoints | 10.10.50.0/24 · .1 | h8 DNS, h9 HTTP, h10 files, h11 finance app |
| 99 | Management | 10.10.99.0/24 · .1 | h12 |

The VLAN and address metadata are defined once in `src/enterprise_config.py`.
Enterprise Mininet mode tags host-facing OVS ports as access ports and sets
switch-to-switch ports as trunks. The controller performs centralized
inter-VLAN forwarding after evaluating the same policy module. The gateway
addresses are controller-proxied in this emulation; this is a teaching
implementation, not a separate hardware router or production DHCP service.

### Access policy enforced by the controller

| Source | Destination | Policy |
|---|---|---|
| Branch users | Shared DNS | Permit TCP/UDP 53 |
| Branch users | Shared HTTP | Permit TCP 80/443 |
| Branch 1 / Branch 2 | Each other | Permit ICMP; deny other inter-branch traffic |
| Finance | Finance application | Permit TCP 8443 and explicit service replies |
| Admin / Finance | File endpoint | Permit TCP 21 and explicit replies |
| Admin / IT | Management endpoint | Permit TCP 22/ICMP and authorized replies |
| Other inter-VLAN pairs | Any | Deny by default |

Denied IPv4 flows receive a higher-priority drop rule. The Mininet policy
test starts HTTP services on the shared web and finance endpoints, checks
permitted HTTP across VLANs, tests permitted branch/IT connectivity, and
checks blocked branch-to-finance and finance-to-management traffic.

### Routing and failover

Static and adaptive controllers retain their existing route algorithms. The
adaptive cost remains `delay + 35 × current_utilization³ × priority_factor
+ 12 × forecast_utilization³ × priority_factor`. OpenFlow port-status events
remove or restore the corresponding known link in the controller graph,
clear cached IPv4 routes, and invalidate installed IPv4 path rules. New
flows are then calculated over the current graph. No LLDP discovery is used;
the controller updates the hardcoded Mininet topology from explicit port
events. The failover script toggles the s5-s8 link, records continuous-ping
loss/recovery, and collects controller link/route timestamps when available.

### Run commands

```bash
# Preserve and run the original baseline
python src/run_experiment.py

# New enterprise graph, separate outputs, and enterprise dashboard data
python src/run_experiment.py --mode enterprise

# Open the standalone dashboard on Windows after generating enterprise data
Start-Process .\index.html

# Fast unit tests for graph, policy, and logical failover behavior
python -m unittest discover -s tests -v

# On Ubuntu/Debian with Mininet, OVS, OS-Ken, and root privileges
cd mininet_sdn
sudo ./run_enterprise_demo.sh static
sudo ./run_enterprise_demo.sh adaptive
```

Live enterprise Mininet runs write controller events to
`mininet_sdn/controller_enterprise.log` and the latest measured failover
details to `results/mininet_failover_latest.json`. The enterprise simulation
also writes policy logic results and a graph-only alternate-path scenario;
those are clearly labeled as simulation output and are not live measurements.
After the Linux scripts run, live policy and failover results are embedded in
the dashboard and saved separately as `results/mininet_policy_latest.json`
and `results/mininet_failover_latest.json`.

### Current scope and limitations

- Enterprise simulation results from this run: 24 intervals × 22 flows,
  5.4% lower mean interval latency, 34.3% lower mean interval peak
  utilization, and 12 static vs 0 adaptive modeled drops. These values are
  separate from the original baseline results.
- Seven enterprise policy logic cases pass; these are unit-level policy
  checks, not packet measurements.
- Ten Python unit tests pass. This Windows environment does not include
  Mininet or OS-Ken, so live VLAN/ACL and link-failure integration tests have
  not been run here.
- Enterprise endpoints use static IP addresses. DHCP is not implemented.
  `h8`, `h10`, and `h11` are configured as DNS/file/finance service endpoints,
  but only the live policy test starts HTTP on h9 and h11. A DNS daemon and
  FTP/file-transfer daemon remain future work.
- The browser dashboard reports generated enterprise simulation data and
  graph failover. It does not display a live controller feed. The live
  Mininet event log and failover JSON are separate artifacts.

### Interactive packet-flow lab

The enterprise section in `index.html` includes a zoomable/pannable network
canvas with device/link inspectors, source/destination and traffic-class
selectors, static/adaptive choices, multiple animated simulated flows,
pause/resume/stop/reset controls, and an event list. Run the enterprise command
above to embed graph-derived topology, route choices, and policy outcomes.
Routes are selected in Python by `select_flow_route` using the controller's
static delay weight or adaptive cost formula, then the standalone browser
animates those saved routes; it does not run a second routing engine. The
optional `s5-s7` congestion/failure choices are graph simulation scenarios.
The canvas does not claim to display real packets, measured per-flow latency,
or live Mininet telemetry.
