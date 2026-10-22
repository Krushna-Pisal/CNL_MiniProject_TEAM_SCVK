# Real Mininet + SDN Deployment

This folder is a genuine SDN deployment, not a simulation: real Mininet
switches, real Open vSwitch, real OpenFlow 1.3 messages, and a real
programmable controller making live routing decisions. It's the
"production-shaped" version of the pure-Python simulation in `../src/`
(same topology, same idea) — build this one if you want to actually run
and click through it live for your teacher.

## What's real vs. simplified

| | This project |
|---|---|
| Switches | Real Open vSwitch instances (`datapath=user`, since kernel-module OVS needs a matching kernel; userspace works identically, just slower) |
| Links | Real Linux veth pairs, real `tc`/`netem` bandwidth+delay shaping |
| Controller | Real OpenFlow controller (`os-ken`, the actively-maintained Ryu-API-compatible fork — original `ryu` no longer installs cleanly on modern Python) |
| Routing | Real per-hop `OFPFlowMod` messages installed switch by switch, computed by real Dijkstra over real, live-measured link utilization |
| ML | Real scikit-learn models: `TrafficClassifier` (pretrained, classifies live flows from real `OFPFlowStatsRequest` data) and `CongestionPredictor` (fit continuously on live `OFPPortStatsRequest` history) |
| Topology discovery | **Hardcoded**, not LLDP-discovered — see Future Work |
| Traffic classification at flow-setup | **Port-based heuristic**, not ML — see Future Work |

## Setup (Ubuntu/Debian, needs root)

```bash
sudo apt-get update
sudo apt-get install -y mininet openvswitch-switch openvswitch-testcontroller iproute2 iputils-ping iperf
pip install -r requirements.txt
python3 train_models.py          # trains + pickles the traffic classifier
```

If your kernel has the `openvswitch` module available, OVS will use it
automatically and you can drop `datapath="user"` from `network_topo.py` for
better performance. On systems without systemd (some containers/minimal
VMs), start OVS manually first: `sudo bash start_ovs.sh`.

## Run it

```bash
sudo ./run_demo.sh static      # baseline: classic non-adaptive shortest path
sudo ./run_demo.sh adaptive    # the AI-driven controller
```

Each saturates the `s2–s4` link with a real 60 Mbps bulk iperf transfer,
then opens a new voice-class flow from `h2` to `h5` while that congestion
is happening, and prints which path the controller chose.

**What we actually captured running this** (saved in `sample_run_logs/` in
case you can't run it live during your demo):

```
# STATIC — routes the new voice flow through the already-congested link:
[static] 10.0.0.2 -> 10.0.0.4 routed via switches [2, 4, 7, 6]   <- bulk flow congests s2-s4
[static] 10.0.0.2 -> 10.0.0.5 routed via switches [2, 4, 7]      <- voice flow sent through it anyway

# ADAPTIVE — detects the real congestion and reroutes around it:
[adaptive] 10.0.0.2:55367 -> 10.0.0.4:5001 class=bulk  priority=4 path=[2, 4, 7, 6]
[adaptive][live-ML] flow classified as 'bulk' (demand=61.50Mbps, pkt_size=1512B, duration=7.5s)
[adaptive] 10.0.0.2:50331 -> 10.0.0.5:5060 class=voice priority=1 path=[2, 5, 7]   <- avoided s2-s4!
```

The `[adaptive][live-ML]` lines are the pretrained Random Forest classifier
running on real byte/packet counters pulled from the switches mid-transfer
— not synthetic data — correctly identifying the bulk flow and its real
measured throughput.

## Also try

- `sudo python3 network_topo.py` — brings up the full topology and drops
  into the Mininet CLI so you can run your own `pingall`, `iperf`, `dpctl
  dump-flows`, etc.
- `sudo python3 test_static_run.py` / `test_adaptive_run.py` — simple
  multi-hop connectivity check across the whole mesh.

## Project structure

```
├── network_topo.py            Mininet topology (8 switches, 6 hosts) + config dumper
├── network_config.json        pre-generated port/adjacency map (topology is deterministic)
├── common.py                  shared graph/host lookup loader for both controllers
├── controller_static.py       baseline: non-adaptive shortest-path controller
├── controller_adaptive.py     AI-driven: live congestion forecasting + adaptive routing
├── traffic_classes.py         port -> traffic class/priority mapping
├── ml_models.py                TrafficClassifier + CongestionPredictor (same as ../src/)
├── train_models.py            offline training step, produces models/classifier.pkl
├── osken_run.py                minimal os-ken app launcher (this build has no CLI script)
├── start_ovs.sh / run_demo.sh  setup + one-command demo runner
├── test_*.py                   connectivity + congestion-avoidance test scripts
└── sample_run_logs/            real captured output from an actual run, as a fallback
```

## Enterprise VLAN / security / failover mode

The original six-host demo is still the default. Enterprise mode is opt-in
and reuses the eight switches while adding 14 department, branch, and service
hosts plus three redundant switch links. Sites are HQ (s1-s4), Branch 1
(s5, s7), and Branch 2 (s6, s8). Host links are OVS access ports; switch
links carry VLANs 10, 20, 30, 40, 41, 50, and 99 as trunks.

| VLAN | Segment | Subnet / gateway |
|---:|---|---|
| 10 | Administration | 10.10.10.0/24 · 10.10.10.1 |
| 20 | Finance | 10.10.20.0/24 · 10.10.20.1 |
| 30 | IT | 10.10.30.0/24 · 10.10.30.1 |
| 40 | Branch 1 users | 10.10.40.0/24 · 10.10.40.1 |
| 41 | Branch 2 users | 10.10.41.0/24 · 10.10.41.1 |
| 50 | Shared service endpoints | 10.10.50.0/24 · 10.10.50.1 |
| 99 | Management | 10.10.99.0/24 · 10.10.99.1 |

Static controller-proxied gateway addresses make the separate subnets
reachable through the central OpenFlow controller. A default-deny policy is
enforced before IPv4 routes are installed. Branches may use DNS (TCP/UDP 53)
and HTTP(S) (TCP 80/443); finance may use the finance endpoint (TCP 8443);
admin/finance may use the file endpoint (TCP 21); admin/IT may use
management. Branch-to-branch ICMP is permitted; other inter-branch traffic
is denied. Authorized service replies are allowed by service role and source
port. The policy code is shared with the Python enterprise experiment.

Run both controller variants and live integration checks from this directory
on Ubuntu/Debian as root:

```bash
pip install -r requirements.txt
python3 train_models.py
sudo ./run_enterprise_demo.sh static
sudo ./run_enterprise_demo.sh adaptive
```

The runner generates `network_config_enterprise.json` from actual Mininet
port assignments before starting the controller. The policy test starts HTTP
servers on h9 (port 80) and h11 (port 8443), verifies permitted cross-VLAN
requests, checks allowed branch/IT traffic, and checks denied access. The
failover test runs continuous ping from h4 to h6, disables and restores
s5-s8, and records packet loss, first successful reply after restoration,
and controller link/route event timestamps. Results are saved to
`../results/mininet_failover_latest.json`; controller events are recorded in
`controller_enterprise.log`. The measured policy and failover payloads are
also embedded in the self-contained root dashboard after each script runs.

This live path has not been executed on Windows. Use the Linux integration
run to measure actual detection, route recomputation, and recovery time; the
Python enterprise graph run reports only logical alternate paths. LLDP is
not implemented: the controller updates its known graph from OpenFlow port
status events. IP addresses are static. DHCP and DNS/file-transfer daemons
are not configured; h8/h10 are reserved endpoint roles, while this demo
starts HTTP only for its access-control checks.

## Honest limitations / Future Work

- **Topology is hardcoded**, not discovered via LLDP. A production controller
  would use `os_ken.topology.api` to discover switches/links dynamically;
  hardcoding keeps this project's code focused on the ML/routing logic. Since
  the Mininet topology is deterministic, `network_config.json` only needs to
  be regenerated (`python3 network_topo.py --no-cli`) if you change the topology.
- **Initial flow priority is port-based**, not ML-based, because the
  classifier needs a few packets of history (packet size, inter-arrival
  time) to have any features to classify on — a chicken-and-egg problem at
  the very first packet of a brand-new flow. The trained classifier *is*
  genuinely used, continuously, against live flow statistics (see the
  `[live-ML]` log lines) — using its output to trigger rerouting an
  already-established flow (flow migration) rather than just logging it is
  the natural next step.
- **Userspace OVS datapath** was used because this environment's kernel
  doesn't have the `openvswitch` kernel module. It's functionally identical
  but much slower than the kernel datapath, which is why you may see a
  handful of duplicate controller round-trips for the same flow under high
  packet rates before the fast-path rule takes effect (mitigated here with
  a simple software-side dedup cache) — a real deployment on a normal Linux
  box or hardware switch installs the rule in microseconds and won't show this.
- **`tc`/`netem` bandwidth shaping** may log `Error: Specified qdisc kind is
  unknown` on some constrained kernels (including the sandbox this was
  developed in) — links still work, just without precise rate-limiting on
  those kernels. A standard Ubuntu desktop/VM kernel has full `netem` support.
