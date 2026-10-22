"""
common.py
Shared by both controller apps: loads network_config.json (written by
network_topo.py) and builds the networkx graph + lookup tables the
controllers route with.
"""

import json
import os
import sys
import networkx as nx

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "src"))
from enterprise_config import policy_allows

CONFIG_NAME = "network_config_enterprise.json" if os.environ.get("SDN_ENTERPRISE") == "1" else "network_config.json"
CONFIG_PATH = os.path.join(os.path.dirname(__file__), CONFIG_NAME)


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


def update_link_state(G, cfg, dpid, port, up):
    """Apply one explicit OpenFlow port-state event to the known graph.

    Returns the affected switch pair, or None for a host-facing/unknown port.
    Link metadata and port maps come from the same topology config used to
    create the Mininet links.
    """
    for link in cfg.get("links", []):
        if (link["dpid1"] == dpid and link["port1"] == port) or (
            link["dpid2"] == dpid and link["port2"] == port
        ):
            a, b = link["dpid1"], link["dpid2"]
            if up:
                if G.has_edge(a, b):
                    return None
                G.add_edge(a, b, capacity_mbps=link["capacity_mbps"],
                           delay_ms=link["delay_ms"],
                           port_map={a: link["port1"], b: link["port2"]})
            elif not G.has_edge(a, b):
                return None
            else:
                G.remove_edge(a, b)
            return a, b
    return None


def allowed_enterprise_flow(cfg, src_ip, dst_ip, protocol, dst_port, src_port=0):
    """Return (allowed, reason) using host VLAN/role metadata from config."""
    hosts = {host["ip"]: host for host in cfg.get("hosts", [])}
    src, dst = hosts.get(src_ip), hosts.get(dst_ip)
    if src is None or dst is None:
        return False, "unknown_endpoint"
    if cfg.get("mode") != "enterprise":
        return True, "baseline"
    return policy_allows(src, dst, protocol, dst_port, src_port), "enterprise_acl"


def host_record(cfg, ip):
    return next((host for host in cfg.get("hosts", []) if host.get("ip") == ip), None)


def gateway_record(cfg, ip):
    return next((gateway for gateway in cfg.get("gateways", []) if gateway.get("ip") == ip), None)


def validate_enterprise_source(cfg, dpid, port, src_ip, src_mac, vlan_id):
    """Bind enterprise source identity to its configured VLAN/access port."""
    if cfg.get("mode") != "enterprise":
        return True, "baseline"
    host = host_record(cfg, src_ip)
    if host is None:
        return False, "unknown_source"
    if host.get("dpid") == dpid and host.get("port") == port:
        if vlan_id is not None and int(vlan_id) != int(host["vlan"]):
            return False, "source_vlan_mismatch"
        if src_mac.lower() != host.get("mac", "").lower():
            return False, "source_mac_mismatch"
        return True, "host_access_port"
    if vlan_id is None or int(vlan_id) != int(host["vlan"]):
        return False, "source_vlan_mismatch"
    if any((link.get("dpid1") == dpid and link.get("port1") == port) or
           (link.get("dpid2") == dpid and link.get("port2") == port)
           for link in cfg.get("links", [])):
        return True, "switch_trunk"
    return False, "unknown_ingress_port"


def make_flow_match(parser, cfg, src_ip, dst_ip, proto=None, src_port=None, dst_port=None):
    fields = {"eth_type": 0x0800, "ipv4_src": src_ip, "ipv4_dst": dst_ip}
    source = host_record(cfg, src_ip)
    if cfg.get("mode") == "enterprise" and source and source.get("vlan") is not None:
        fields["vlan_vid"] = 0x1000 | int(source["vlan"])
    protocol_numbers = {"tcp": 6, "udp": 17, "icmp": 1}
    if proto in protocol_numbers:
        fields["ip_proto"] = protocol_numbers[proto]
    if proto in {"tcp", "udp"}:
        fields["tcp_src" if proto == "tcp" else "udp_src"] = src_port
        fields["tcp_dst" if proto == "tcp" else "udp_dst"] = dst_port
    return parser.OFPMatch(**fields)


def install_path_flows(G, path, datapaths, cfg, src_ip, dst_ip, final_out_port,
                       priority=10, proto=None, src_port=None, dst_port=None):
    """Install hop rules and return the source switch's first output port."""
    src = host_record(cfg, src_ip)
    dst = host_record(cfg, dst_ip)
    cross_vlan = cfg.get("mode") == "enterprise" and src and dst and src.get("vlan") != dst.get("vlan")
    first_out_port = final_out_port
    for index, dpid in enumerate(path):
        dp = datapaths.get(dpid)
        if dp is None:
            continue
        parser, ofp = dp.ofproto_parser, dp.ofproto
        out_port = (out_port_on(G, dpid, path[index + 1]) if index < len(path) - 1
                    else final_out_port)
        if index == 0:
            first_out_port = out_port
        actions = []
        if cross_vlan:
            actions.extend([
                parser.OFPActionSetField(eth_src=cfg["gateways"][0]["mac"]),
                parser.OFPActionSetField(eth_dst=dst["mac"]),
            ])
            if index == 0:
                actions.append(parser.OFPActionDecNwTtl())
            if index == len(path) - 1:
                actions.append(parser.OFPActionSetField(vlan_vid=0x1000 | int(dst["vlan"])))
        actions.append(parser.OFPActionOutput(out_port))
        match = make_flow_match(parser, cfg, src_ip, dst_ip, proto, src_port, dst_port)
        instructions = [parser.OFPInstructionActions(ofp.OFPIT_APPLY_ACTIONS, actions)]
        mod = parser.OFPFlowMod(datapath=dp, priority=priority, match=match,
                                instructions=instructions, idle_timeout=30)
        dp.send_msg(mod)
    return first_out_port


def first_packet_actions(parser, out_port, cfg, src_ip, dst_ip):
    src, dst = host_record(cfg, src_ip), host_record(cfg, dst_ip)
    actions = []
    if cfg.get("mode") == "enterprise" and src and dst and src.get("vlan") != dst.get("vlan"):
        actions.extend([
            parser.OFPActionSetField(eth_src=cfg["gateways"][0]["mac"]),
            parser.OFPActionSetField(eth_dst=dst["mac"]),
            parser.OFPActionDecNwTtl(),
        ])
    actions.append(parser.OFPActionOutput(out_port))
    return actions


def delete_ipv4_flows(datapaths):
    """Remove path rules after a topology change; retain the table-miss rule."""
    for dp in datapaths.values():
        parser, ofp = dp.ofproto_parser, dp.ofproto
        dp.send_msg(parser.OFPFlowMod(
            datapath=dp, command=ofp.OFPFC_DELETE, out_port=ofp.OFPP_ANY,
            out_group=ofp.OFPG_ANY, match=parser.OFPMatch(eth_type=0x0800),
        ))
