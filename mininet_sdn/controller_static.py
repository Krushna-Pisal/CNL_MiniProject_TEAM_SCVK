"""
controller_static.py
Baseline controller: real OpenFlow, real per-hop flow installation, real
ARP proxying -- but routing is the "classic" non-adaptive kind. Every path
is Dijkstra shortest-path by fixed link delay only, computed once and never
revisited, exactly like a distributed protocol such as OSPF would behave.
It never looks at current load or forecasted congestion.

Run with the launcher (from mininet_sdn/):
    python3 osken_run.py controller_static
"""

import networkx as nx
from os_ken.base import app_manager
from os_ken.controller import ofp_event
from os_ken.controller.handler import CONFIG_DISPATCHER, MAIN_DISPATCHER, set_ev_cls
from os_ken.ofproto import ofproto_v1_3
from os_ken.lib.packet import packet, ethernet, arp, ipv4, ether_types

from common import load_network, out_port_on


class StaticShortestPathController(app_manager.OSKenApp):
    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.G, self.mac_to_attach, self.ip_to_attach, self.cfg = load_network()
        self.datapaths = {}
        self.installed_flows = {}  # (dpid, ip_src, ip_dst) -> first_hop_out_port -- avoids
                                       # redundant recomputation if the switch's software
                                       # datapath punts a few extra packets before its new
                                       # flow-mod takes effect (common under high packet
                                       # rate with the userspace OVS datapath used here)
        print(f"[static] loaded topology: {self.G.number_of_nodes()} switches, "
              f"{self.G.number_of_edges()} links, {len(self.ip_to_attach)} hosts")

    # ---------------- switch connect ----------------
    @set_ev_cls(ofp_event.EventOFPSwitchFeatures, CONFIG_DISPATCHER)
    def switch_features_handler(self, ev):
        dp = ev.msg.datapath
        self.datapaths[dp.id] = dp
        ofp, parser = dp.ofproto, dp.ofproto_parser
        match = parser.OFPMatch()
        actions = [parser.OFPActionOutput(ofp.OFPP_CONTROLLER, ofp.OFPCML_NO_BUFFER)]
        self._add_flow(dp, 0, match, actions)
        print(f"[static] switch connected: dpid={dp.id}")

    def _add_flow(self, dp, priority, match, actions, idle_timeout=0):
        ofp, parser = dp.ofproto, dp.ofproto_parser
        inst = [parser.OFPInstructionActions(ofp.OFPIT_APPLY_ACTIONS, actions)]
        mod = parser.OFPFlowMod(datapath=dp, priority=priority, match=match,
                                 instructions=inst, idle_timeout=idle_timeout)
        dp.send_msg(mod)

    # ---------------- path computation (STATIC: delay-only, never changes) ----------------
    def _compute_path(self, src_dpid, dst_dpid):
        return nx.shortest_path(self.G, src_dpid, dst_dpid, weight="delay_ms")

    def _install_path(self, path, match_kwargs, priority=10):
        """Install a flow rule on every switch along `path` matching
        match_kwargs, outputting toward the next hop (or the final host
        port on the last switch)."""
        match_kwargs = dict(match_kwargs)
        final_out_port = match_kwargs.pop("_final_out_port")
        for i, dpid in enumerate(path):
            dp = self.datapaths.get(dpid)
            if dp is None:
                continue
            parser = dp.ofproto_parser
            if i < len(path) - 1:
                out_port = out_port_on(self.G, dpid, path[i + 1])
            else:
                out_port = final_out_port
            match = parser.OFPMatch(**match_kwargs)
            actions = [parser.OFPActionOutput(out_port)]
            self._add_flow(dp, priority, match, actions, idle_timeout=30)

    # ---------------- packet-in: ARP proxy + first-packet routing ----------------
    @set_ev_cls(ofp_event.EventOFPPacketIn, MAIN_DISPATCHER)
    def packet_in_handler(self, ev):
        msg = ev.msg
        dp = msg.datapath
        ofp, parser = dp.ofproto, dp.ofproto_parser
        in_port = msg.match["in_port"]
        pkt = packet.Packet(msg.data)
        eth = pkt.get_protocols(ethernet.ethernet)[0]

        if eth.ethertype == ether_types.ETH_TYPE_ARP:
            self._handle_arp(dp, in_port, pkt, msg)
            return

        if eth.ethertype == ether_types.ETH_TYPE_IP:
            self._handle_ip(dp, in_port, pkt, msg)
            return

    def _handle_arp(self, dp, in_port, pkt, msg):
        """Controller-mediated ARP: we know every host's MAC, so we reply
        directly instead of flooding across the mesh (flooding a graph with
        redundant paths would create broadcast loops)."""
        ofp, parser = dp.ofproto, dp.ofproto_parser
        arp_pkt = pkt.get_protocols(arp.arp)[0]
        if arp_pkt.opcode != arp.ARP_REQUEST:
            return
        target_ip = arp_pkt.dst_ip
        if target_ip not in self.ip_to_attach:
            return
        _, _, target_mac = self.ip_to_attach[target_ip]

        eth = pkt.get_protocols(ethernet.ethernet)[0]
        reply_eth = ethernet.ethernet(dst=eth.src, src=target_mac, ethertype=ether_types.ETH_TYPE_ARP)
        reply_arp = arp.arp(opcode=arp.ARP_REPLY, src_mac=target_mac, src_ip=target_ip,
                             dst_mac=arp_pkt.src_mac, dst_ip=arp_pkt.src_ip)
        reply = packet.Packet()
        reply.add_protocol(reply_eth)
        reply.add_protocol(reply_arp)
        reply.serialize()
        out = parser.OFPPacketOut(
            datapath=dp, buffer_id=ofp.OFP_NO_BUFFER, in_port=ofp.OFPP_CONTROLLER,
            actions=[parser.OFPActionOutput(in_port)], data=reply.data)
        dp.send_msg(out)

    def _handle_ip(self, dp, in_port, pkt, msg):
        ofp, parser = dp.ofproto, dp.ofproto_parser
        ip_pkt = pkt.get_protocols(ipv4.ipv4)[0]
        src_ip, dst_ip = ip_pkt.src, ip_pkt.dst

        if dst_ip not in self.ip_to_attach:
            return  # unknown destination, drop silently

        dst_dpid, dst_port, _ = self.ip_to_attach[dst_ip]
        src_dpid = dp.id

        cache_key = (src_dpid, src_ip, dst_ip)
        if cache_key in self.installed_flows:
            out_port = self.installed_flows[cache_key]
            out = parser.OFPPacketOut(
                datapath=dp, buffer_id=msg.buffer_id, in_port=in_port,
                actions=[parser.OFPActionOutput(out_port)],
                data=None if msg.buffer_id != ofp.OFP_NO_BUFFER else msg.data)
            dp.send_msg(out)
            return

        if src_dpid == dst_dpid:
            path = [src_dpid]
        else:
            path = self._compute_path(src_dpid, dst_dpid)

        match_kwargs = dict(eth_type=ether_types.ETH_TYPE_IP, ipv4_src=src_ip, ipv4_dst=dst_ip,
                             _final_out_port=dst_port)
        self._install_path(path, match_kwargs)
        print(f"[static] {src_ip} -> {dst_ip} routed via switches {path}")

        # forward the packet that triggered this immediately (don't drop it
        # while the flow rules above are still being pushed)
        out_port = out_port_on(self.G, src_dpid, path[1]) if len(path) > 1 else dst_port
        self.installed_flows[cache_key] = out_port
        out = parser.OFPPacketOut(
            datapath=dp, buffer_id=msg.buffer_id, in_port=in_port,
            actions=[parser.OFPActionOutput(out_port)],
            data=None if msg.buffer_id != ofp.OFP_NO_BUFFER else msg.data)
        dp.send_msg(out)
