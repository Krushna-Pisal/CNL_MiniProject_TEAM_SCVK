"""
network_topo.py
Builds the REAL Mininet network (actual switches, actual veth links with real
bandwidth/delay via Linux tc, actual hosts with real network namespaces) that
mirrors the topology used in the pure-simulation version of this project.

Run directly to bring the network up and drop into the Mininet CLI:

    sudo python3 network_topo.py

It also writes network_config.json, which both SDN controller apps
(controller_static.py / controller_adaptive.py) load at startup so they know
the switch-to-switch adjacency, port numbers, and host attachment points --
this project hardcodes topology instead of using LLDP discovery, which keeps
the controller code focused on the routing/ML logic (see README for the
production alternative).
"""

import json
import argparse

from mininet.net import Mininet
from mininet.node import OVSSwitch, RemoteController
from mininet.link import TCLink
from mininet.cli import CLI
from mininet.log import setLogLevel, info

# same numbers as the simulation's topology.py, so results are comparable
CORE_LINKS = [
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

EDGE_LINKS = [
    ("h1", "s1"),
    ("h2", "s2"),
    ("h3", "s3"),
    ("h4", "s6"),
    ("h5", "s7"),
    ("h6", "s8"),
]

HOST_IPS = {
    "h1": "10.0.0.1", "h2": "10.0.0.2", "h3": "10.0.0.3",
    "h4": "10.0.0.4", "h5": "10.0.0.5", "h6": "10.0.0.6",
}


def build_net(controller_ip="127.0.0.1", controller_port=6653):
    net = Mininet(switch=OVSSwitch, link=TCLink, autoSetMacs=True, build=False)

    net.addController("c0", controller=RemoteController, ip=controller_ip, port=controller_port)

    switches = {}
    for i in range(1, 9):
        name = f"s{i}"
        switches[name] = net.addSwitch(name, datapath="user", protocols="OpenFlow13")

    hosts = {}
    for name, ip in HOST_IPS.items():
        hosts[name] = net.addHost(name, ip=ip + "/24")

    link_records = []
    for u, v, bw, delay_ms in CORE_LINKS:
        link = net.addLink(switches[u], switches[v], bw=bw, delay=f"{delay_ms}ms")
        link_records.append(("switch", u, v, bw, delay_ms, link))

    for h, s in EDGE_LINKS:
        link = net.addLink(hosts[h], switches[s], bw=1000, delay="0.5ms")
        link_records.append(("host", h, s, 1000, 0.5, link))

    net.build()
    net.start()

    # ---- work out the real port numbers Mininet/OVS assigned ----
    config = {"links": [], "hosts": [], "switch_dpids": {}}
    for name, sw in switches.items():
        config["switch_dpids"][name] = int(sw.dpid, 16)

    for kind, a, b, bw, delay_ms, link in link_records:
        if kind == "switch":
            sw_a, sw_b = switches[a], switches[b]
            port_a = sw_a.ports[link.intf1]
            port_b = sw_b.ports[link.intf2]
            config["links"].append({
                "dpid1": int(sw_a.dpid, 16), "port1": port_a,
                "dpid2": int(sw_b.dpid, 16), "port2": port_b,
                "capacity_mbps": bw, "delay_ms": delay_ms,
                "name1": a, "name2": b,
            })
        else:
            host, sw = hosts[a], switches[b]
            port_on_switch = sw.ports[link.intf2]
            config["hosts"].append({
                "name": a, "ip": HOST_IPS[a], "mac": host.MAC(),
                "dpid": int(sw.dpid, 16), "port": port_on_switch,
            })

    with open("network_config.json", "w") as f:
        json.dump(config, f, indent=2)
    info(f"*** wrote network_config.json ({len(config['links'])} switch links, "
         f"{len(config['hosts'])} hosts)\n")

    return net


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--controller-ip", default="127.0.0.1")
    parser.add_argument("--controller-port", type=int, default=6653)
    parser.add_argument("--no-cli", action="store_true", help="build+dump config then exit (no interactive CLI)")
    args = parser.parse_args()

    setLogLevel("info")
    net = build_net(args.controller_ip, args.controller_port)
    if not args.no_cli:
        CLI(net)
    net.stop()
