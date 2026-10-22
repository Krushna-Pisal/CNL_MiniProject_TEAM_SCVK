"""
common.py
Shared by both controller apps: loads network_config.json (written by
network_topo.py) and builds the networkx graph + lookup tables the
controllers route with.
"""

import json
import os
import networkx as nx

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "network_config.json")


def load_network(path=CONFIG_PATH):
    """Loads the topology into a networkx graph. Every edge carries a
    `port_map` dict {dpid: port_on_that_switch_facing_the_other_end}, so a
    controller always knows exactly which OpenFlow port to output on."""
    with open(path) as f:
        cfg = json.load(f)

    G = nx.Graph()
    for link in cfg["links"]:
        d1, d2 = link["dpid1"], link["dpid2"]
        G.add_edge(d1, d2,
                   capacity_mbps=link["capacity_mbps"],
                   delay_ms=link["delay_ms"],
                   port_map={d1: link["port1"], d2: link["port2"]})

    mac_to_attach = {}
    ip_to_attach = {}
    for h in cfg["hosts"]:
        mac_to_attach[h["mac"]] = (h["dpid"], h["port"], h["ip"])
        ip_to_attach[h["ip"]] = (h["dpid"], h["port"], h["mac"])

    return G, mac_to_attach, ip_to_attach, cfg


def out_port_on(G, dpid_here, dpid_next):
    """Which OpenFlow port on switch `dpid_here` faces switch `dpid_next`."""
    return G[dpid_here][dpid_next]["port_map"][dpid_here]
