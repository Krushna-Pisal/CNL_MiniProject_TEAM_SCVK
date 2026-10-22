"""
controller_adaptive.py
The AI-driven controller. Same real OpenFlow plumbing as the static
baseline (ARP proxy, per-hop flow install), but:

  1. Every flow's initial priority is assigned by port-based classification
     (traffic_classes.classify_by_port) -- instant, needed at flow setup.
  2. A background loop polls REAL port statistics from every connected
     switch (OFPPortStatsRequest) every POLL_INTERVAL seconds, turns them
     into a live per-link utilization time series, and periodically fits
     the same CongestionPredictor used in the simulation to forecast next-
     interval utilization for every link.
  3. Path selection re-weights every link by:
         cost = base_delay + (current_util^3 + forecast_util^3) * priority_factor
     and recomputes Dijkstra per new flow, so different flows can take
     different paths depending on real, currently-measured congestion.
  4. A second background loop polls REAL per-flow statistics
     (OFPFlowStatsRequest) and runs the pretrained Random Forest
     TrafficClassifier (models/classifier.pkl) on the resulting live
     packet-size / inter-arrival / demand features, logging what the model
     thinks each active flow actually is -- the ML model operating on real
     network telemetry, not synthetic data.

Run with the launcher (from mininet_sdn/):
    python3 osken_run.py controller_adaptive
"""

import os
import pickle
import time

import networkx as nx
import numpy as np
import pandas as pd

from os_ken.base import app_manager
from os_ken.controller import ofp_event
from os_ken.controller.handler import CONFIG_DISPATCHER, MAIN_DISPATCHER, set_ev_cls
from os_ken.ofproto import ofproto_v1_3
from os_ken.lib import hub
from os_ken.lib.packet import packet, ethernet, arp, ipv4, tcp, udp, ether_types

from common import load_network, out_port_on
from ml_models import CongestionPredictor
from traffic_classes import classify_by_port

POLL_INTERVAL = 3          # seconds between port-stats polls
FLOW_POLL_INTERVAL = 6     # seconds between flow-stats polls (for the ML classifier)
PRIORITY_FACTOR = {1: 1.6, 2: 1.3, 3: 1.0, 4: 0.7}
MODELS_DIR = os.path.join(os.path.dirname(__file__), "models")


class AdaptiveMLController(app_manager.OSKenApp):
    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.G, self.mac_to_attach, self.ip_to_attach, self.cfg = load_network()
        self.datapaths = {}
        self.installed_flows = {}  # (dpid, ip_src, ip_dst, proto) -> first_hop_out_port
                                    # avoids redundant recomputation if the switch's
                                    # software datapath punts a few extra packets before
                                    # its new flow-mod takes effect (common under high
                                    # packet rate with the userspace OVS datapath used here)

        # dpid,port -> neighbor dpid, for turning port stats into edge utilization
        self.port_to_neighbor = {}
        for d1, d2, data in self.G.edges(data=True):
            self.port_to_neighbor[(d1, data["port_map"][d1])] = d2
            self.port_to_neighbor[(d2, data["port_map"][d2])] = d1

        self.last_port_bytes = {}          # (dpid, port) -> (tx_bytes, timestamp)
        self.edge_util_history = {}        # frozenset({d1,d2}) -> [utilization %, ...]
        self.edge_forecast = {}            # frozenset({d1,d2}) -> forecast %
        self.congestion_predictor = CongestionPredictor(window=4)

        clf_path = os.path.join(MODELS_DIR, "classifier.pkl")
        if os.path.exists(clf_path):
            with open(clf_path, "rb") as f:
                self.classifier = pickle.load(f)
            print("[adaptive] loaded pretrained traffic classifier")
        else:
            self.classifier = None
            print("[adaptive] WARNING: no trained classifier found, run train_models.py first")

        self.flow_baseline = {}  # (dpid, cookie) -> (byte_count, packet_count, ts) for delta stats

        print(f"[adaptive] loaded topology: {self.G.number_of_nodes()} switches, "
              f"{self.G.number_of_edges()} links, {len(self.ip_to_attach)} hosts")

        self.monitor_thread = hub.spawn(self._port_stats_loop)
        self.flow_monitor_thread = hub.spawn(self._flow_stats_loop)

    # ---------------- switch connect ----------------
    @set_ev_cls(ofp_event.EventOFPSwitchFeatures, CONFIG_DISPATCHER)
    def switch_features_handler(self, ev):
        dp = ev.msg.datapath
        self.datapaths[dp.id] = dp
        ofp, parser = dp.ofproto, dp.ofproto_parser
        match = parser.OFPMatch()
        actions = [parser.OFPActionOutput(ofp.OFPP_CONTROLLER, ofp.OFPCML_NO_BUFFER)]
        self._add_flow(dp, 0, match, actions)
        print(f"[adaptive] switch connected: dpid={dp.id}")

    def _add_flow(self, dp, priority, match, actions, idle_timeout=0):
        ofp, parser = dp.ofproto, dp.ofproto_parser
        inst = [parser.OFPInstructionActions(ofp.OFPIT_APPLY_ACTIONS, actions)]
        mod = parser.OFPFlowMod(datapath=dp, priority=priority, match=match,
                                 instructions=inst, idle_timeout=idle_timeout)
        dp.send_msg(mod)

    # ---------------- background: real port-stats polling -> congestion forecast ----------------
    def _port_stats_loop(self):
        while True:
            for dp in list(self.datapaths.values()):
                parser = dp.ofproto_parser
                ofp = dp.ofproto
                req = parser.OFPPortStatsRequest(dp, 0, ofp.OFPP_ANY)
                dp.send_msg(req)
            hub.sleep(POLL_INTERVAL)

    @set_ev_cls(ofp_event.EventOFPPortStatsReply, MAIN_DISPATCHER)
    def port_stats_reply_handler(self, ev):
        dp = ev.msg.datapath
        now = time.time()
        for stat in ev.msg.body:
            key = (dp.id, stat.port_no)
            neighbor = self.port_to_neighbor.get(key)
            if neighbor is None:
                continue  # host-facing port, not part of the switch mesh
            edge_key = frozenset({dp.id, neighbor})
            cap_mbps = self.G[dp.id][neighbor]["capacity_mbps"]

            prev = self.last_port_bytes.get(key)
            self.last_port_bytes[key] = (stat.tx_bytes, now)
            if prev is None:
                continue
            prev_bytes, prev_ts = prev
            dt = now - prev_ts
            if dt <= 0:
                continue
            mbps = ((stat.tx_bytes - prev_bytes) * 8 / dt) / 1e6
            util_pct = max(0.0, min(100.0, 100.0 * mbps / cap_mbps))

            hist = self.edge_util_history.setdefault(edge_key, [])
            hist.append(util_pct)
            hist[:] = hist[-50:]  # bound memory

            if len(hist) >= self.congestion_predictor.window + 3:
                arr = np.array(hist)
                self.congestion_predictor.fit(arr)
                forecast = self.congestion_predictor.predict_next(arr[-self.congestion_predictor.window:])
                self.edge_forecast[edge_key] = max(0.0, forecast)

    def _current_util(self, d1, d2):
        return (self.edge_util_history.get(frozenset({d1, d2})) or [0.0])[-1]

    def _forecast_util(self, d1, d2):
        return self.edge_forecast.get(frozenset({d1, d2}), 0.0)

    # ---------------- adaptive path computation ----------------
    def _compute_path(self, src_dpid, dst_dpid, priority):
        pfactor = PRIORITY_FACTOR[priority]

        def weight(u, v, data):
            util = self._current_util(u, v) / 100.0
            forecast = self._forecast_util(u, v) / 100.0
            congestion_term = (util ** 3) * 35 + (forecast ** 3) * 12
            return data["delay_ms"] + congestion_term * pfactor

        return nx.shortest_path(self.G, src_dpid, dst_dpid, weight=weight)

    def _install_path(self, path, match_kwargs, priority=10):
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

    # ---------------- packet-in ----------------
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
            return
        dst_dpid, dst_port, _ = self.ip_to_attach[dst_ip]
        src_dpid = dp.id

        # ---- classify by port for immediate priority assignment ----
        proto = "other"
        sport = dport = 0
        t = pkt.get_protocols(tcp.tcp)
        u = pkt.get_protocols(udp.udp)
        if t:
            proto, sport, dport = "tcp", t[0].src_port, t[0].dst_port
        elif u:
            proto, sport, dport = "udp", u[0].src_port, u[0].dst_port

        cache_key = (src_dpid, src_ip, dst_ip, proto, dport)
        if cache_key in self.installed_flows:
            # flow rule already installed for this exact 5-tuple class; the
            # switch's software datapath just hasn't caught up yet -- forward
            # this packet without recomputing/reinstalling anything
            out_port = self.installed_flows[cache_key]
            out = parser.OFPPacketOut(
                datapath=dp, buffer_id=msg.buffer_id, in_port=in_port,
                actions=[parser.OFPActionOutput(out_port)],
                data=None if msg.buffer_id != ofp.OFP_NO_BUFFER else msg.data)
            dp.send_msg(out)
            return

        traffic_class, priority = classify_by_port(proto, sport, dport)

        if src_dpid == dst_dpid:
            path = [src_dpid]
        else:
            path = self._compute_path(src_dpid, dst_dpid, priority)

        match_kwargs = dict(eth_type=ether_types.ETH_TYPE_IP, ipv4_src=src_ip, ipv4_dst=dst_ip,
                             _final_out_port=dst_port)
        if proto in ("tcp", "udp"):
            match_kwargs["ip_proto"] = 6 if proto == "tcp" else 17
        self._install_path(path, match_kwargs, priority=10 + (5 - priority))
        print(f"[adaptive] {src_ip}:{sport} -> {dst_ip}:{dport} "
              f"class={traffic_class} priority={priority} path={path}")

        out_port = out_port_on(self.G, src_dpid, path[1]) if len(path) > 1 else dst_port
        self.installed_flows[cache_key] = out_port
        out = parser.OFPPacketOut(
            datapath=dp, buffer_id=msg.buffer_id, in_port=in_port,
            actions=[parser.OFPActionOutput(out_port)],
            data=None if msg.buffer_id != ofp.OFP_NO_BUFFER else msg.data)
        dp.send_msg(out)

    # ---------------- background: real flow-stats polling -> live ML classification ----------------
    def _flow_stats_loop(self):
        while True:
            hub.sleep(FLOW_POLL_INTERVAL)
            for dp in list(self.datapaths.values()):
                parser = dp.ofproto_parser
                dp.send_msg(parser.OFPFlowStatsRequest(dp))

    @set_ev_cls(ofp_event.EventOFPFlowStatsReply, MAIN_DISPATCHER)
    def flow_stats_reply_handler(self, ev):
        if self.classifier is None:
            return
        rows = []
        for stat in ev.msg.body:
            if stat.priority < 10:
                continue  # skip the table-miss rule
            duration = stat.duration_sec + stat.duration_nsec / 1e9
            if duration <= 0.2 or stat.packet_count <= 1:
                continue
            avg_pkt_size = stat.byte_count / max(1, stat.packet_count)
            avg_iat_ms = (duration * 1000) / max(1, stat.packet_count)
            demand_mbps = (stat.byte_count * 8 / duration) / 1e6
            rows.append(dict(
                avg_pkt_size=avg_pkt_size, avg_iat_ms=avg_iat_ms,
                duration_s=duration, demand_mbps=demand_mbps,
                n_packets=stat.packet_count,
            ))
        if not rows:
            return
        df = pd.DataFrame(rows)
        preds = self.classifier.predict(df)
        for pred, row in zip(preds, rows):
            print(f"[adaptive][live-ML] flow classified as '{pred}' "
                  f"(demand={row['demand_mbps']:.2f}Mbps, pkt_size={row['avg_pkt_size']:.0f}B, "
                  f"duration={row['duration_s']:.1f}s)")
