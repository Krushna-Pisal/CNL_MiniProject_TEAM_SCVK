"""
traffic_classes.py
Real packets don't arrive pre-labelled "voice"/"video"/"web"/"bulk", so a
flow needs to be classified the instant its first packet hits the
controller -- before there's any history to run the ML classifier on. Real
QoS systems commonly do exactly this by well-known transport port (that's
what DSCP/CoS marking on enterprise switches is usually keyed off in
practice), so this project uses the same convention for the *initial*
priority assigned at flow-setup:

    UDP 5060      -> voice     (priority 1, most latency sensitive)
    UDP/TCP 5004  -> video     (priority 2)
    TCP 80/8080   -> web       (priority 3)
    TCP 5001      -> bulk      (priority 4, least sensitive)
    anything else -> web       (priority 3, default)

The trained ML TrafficClassifier (ml_models.py) is still real and still
runs on real, live per-flow statistics pulled from the switches
(OFPFlowStatsRequest) -- see controller_adaptive.py's `_poll_flow_stats`.
It reclassifies + logs confidence for every live flow, demonstrating the
model operating on genuine network telemetry rather than synthetic data.
Using its output to also trigger path migration mid-flow is a natural
extension, noted in the README's Future Work section.
"""

PORT_CLASS = {
    5060: ("voice", 1),
    5004: ("video", 2),
    80:   ("web", 3),
    8080: ("web", 3),
    5001: ("bulk", 4),
}

DEFAULT_CLASS = ("web", 3)


def classify_by_port(proto: str, src_port: int, dst_port: int):
    for p in (dst_port, src_port):
        if p in PORT_CLASS:
            return PORT_CLASS[p]
    return DEFAULT_CLASS
