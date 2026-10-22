"""Measure live ping loss/recovery while a branch-to-branch link is toggled."""

import json
import os
import re
import subprocess
import time

import networkx as nx
from mininet.log import setLogLevel

from common import load_network
from dashboard_results import save_live_payload
from network_topo import build_net


def controller_events(path, source_ip, destination_ip):
    events = []
    if not os.path.exists(path):
        return events
    with open(path, encoding="utf-8", errors="replace") as stream:
        for line in stream:
            try:
                event = json.loads(line)
            except (ValueError, TypeError):
                continue
            if event.get("event") == "route_selected" and (
                event.get("source") == source_ip and event.get("destination") == destination_ip
            ):
                events.append(event)
            elif event.get("event") == "link_state":
                events.append(event)
    return events


def main():
    setLogLevel("warning")
    net = build_net(enterprise=True)
    try:
        time.sleep(3)
        src, dst = net.get("h4"), net.get("h6")
        cfg_graph, _mac, ip_map, cfg = load_network()
        src_dpid = ip_map[src.IP()][0]
        dst_dpid = ip_map[dst.IP()][0]
        event_path = os.environ.get("SDN_CONTROLLER_LOG", "controller_enterprise.log")
        prior_events = controller_events(event_path, src.IP(), dst.IP())
        prior_routes = [event for event in prior_events if event.get("event") == "route_selected"]
        initial_route = prior_routes[-1]["path"] if prior_routes else nx.shortest_path(
            cfg_graph, src_dpid, dst_dpid, weight="delay_ms")
        failed_pair = None
        failed_link_names = None
        for left, right in zip(initial_route[:-1], initial_route[1:]):
            if not cfg_graph.has_edge(left, right):
                continue
            candidate = cfg_graph.copy()
            candidate.remove_edge(left, right)
            if not nx.has_path(candidate, src_dpid, dst_dpid):
                continue
            record = next((row for row in cfg["links"]
                           if {row["dpid1"], row["dpid2"]} == {left, right}), None)
            if record:
                failed_pair = (left, right)
                failed_link_names = (record["name1"], record["name2"])
                break
        if failed_pair is None:
            raise RuntimeError("No link on the selected controller route has a reachable alternate")
        target = next(link for link in net.links if
                      {link.intf1.node.name, link.intf2.node.name} == set(failed_link_names))

        ping = src.popen(["ping", "-D", "-i", "0.2", dst.IP()],
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        time.sleep(2)
        down_time = time.time()
        target.intf1.ifconfig("down")
        time.sleep(3)
        up_time = time.time()
        target.intf1.ifconfig("up")
        time.sleep(4)
        ping.terminate()
        try:
            output, _ = ping.communicate(timeout=2)
        except subprocess.TimeoutExpired:
            ping.kill()
            output, _ = ping.communicate()

        sent_match = re.search(r"(\d+) packets transmitted", output)
        received_match = re.search(r"(\d+) (?:packets )?received", output)
        sent = int(sent_match.group(1)) if sent_match else None
        received = int(received_match.group(1)) if received_match else None
        successes = []
        for line in output.splitlines():
            stamp = re.search(r"\[(\d+\.\d+)\].*bytes from", line)
            if stamp:
                successes.append(float(stamp.group(1)))

        # Expected graph path after removing the failed link; actual controller
        # decisions are separately taken from its structured event log.
        failed_graph = cfg_graph.copy()
        a, b = failed_pair
        failed_graph.remove_edge(a, b)
        alternate_route = nx.shortest_path(failed_graph, src_dpid, dst_dpid, weight="delay_ms")

        events = controller_events(event_path, src.IP(), dst.IP())
        down_events = [e for e in events if e.get("event") == "link_state" and not e.get("up")
                       and set(e.get("link", [])) == set(failed_pair)]
        route_before = [e for e in events if e.get("event") == "route_selected"
                        and e.get("source") == src.IP() and e.get("destination") == dst.IP()
                        and e.get("time_unix", 0) < down_time]
        route_after = [e for e in events if e.get("event") == "route_selected"
                       and e.get("source") == src.IP() and e.get("destination") == dst.IP()
                       and down_time < e.get("time_unix", 0) < up_time]
        first_recovery = next((stamp for stamp in successes if stamp >= up_time), None)
        detection_ms = ((down_events[0]["time_unix"] - down_time) * 1000
                        if down_events else None)
        recompute_ms = ((route_after[0]["time_unix"] - down_events[0]["time_unix"]) * 1000
                        if down_events and route_after else None)
        loss_pct = (100 * (sent - received) / sent) if sent and received is not None else None
        payload = {
            "mode": "mininet_measurement",
            "source": src.IP(), "destination": dst.IP(),
            "failed_link": list(failed_link_names),
            "initial_route": initial_route,
            "controller_route_before_failure": route_before[-1].get("path") if route_before else None,
            "alternate_route_after_link_removal": alternate_route,
            "controller_route_after_failure": route_after[0].get("path") if route_after else None,
            "link_down_time_unix": down_time,
            "link_up_time_unix": up_time,
            "detection_time_ms": round(detection_ms, 2) if detection_ms is not None else None,
            "route_recompute_time_ms": round(recompute_ms, 2) if recompute_ms is not None else None,
            "first_success_after_restore_unix": first_recovery,
            "recovery_after_restore_ms": round((first_recovery - up_time) * 1000, 2)
                if first_recovery is not None else None,
            "ping_sent": sent, "ping_received": received,
            "ping_loss_pct": round(loss_pct, 2) if loss_pct is not None else None,
            "link_restored": True,
            "controller_event_log": event_path,
            "ping_output": output,
        }
        output_path = save_live_payload("MININET_FAILOVER", payload,
                                        "mininet_failover_latest.json")
        print(json.dumps(payload, indent=2))
        print("Saved measurement to", output_path)
        if route_after:
            route = route_after[0].get("path", [])
            if any(set(pair) == {a, b} for pair in zip(route[:-1], route[1:])):
                raise SystemExit("Controller selected a route containing the known-down link")
    finally:
        net.stop()


if __name__ == "__main__":
    main()
