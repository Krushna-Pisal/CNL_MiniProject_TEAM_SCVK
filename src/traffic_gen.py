"""
traffic_gen.py
Generates synthetic network flow records, similar to what an SDN controller
would collect from switch flow-tables / sFlow / NetFlow statistics.

Each flow belongs to one of four application classes, each with realistic
(but synthetic) statistical signatures - this mirrors real traffic
classification datasets (e.g. packet size distributions for VoIP vs bulk
transfer vs video streaming are very different).
"""

import numpy as np
import pandas as pd

RNG = np.random.default_rng(42)

TRAFFIC_CLASSES = ["voice", "video", "web", "bulk"]

# (mean_pkt_size_bytes, std, mean_iat_ms, std, mean_duration_s, std, mean_rate_mbps, std)
CLASS_PROFILES = {
    "voice": dict(pkt_size=(160, 20), iat_ms=(20, 4), duration_s=(45, 15), rate_mbps=(0.09, 0.02)),
    "video": dict(pkt_size=(1350, 80), iat_ms=(8, 3), duration_s=(300, 120), rate_mbps=(4.5, 1.5)),
    "web": dict(pkt_size=(600, 250), iat_ms=(15, 10), duration_s=(4, 3), rate_mbps=(1.2, 0.8)),
    "bulk": dict(pkt_size=(1450, 30), iat_ms=(2, 1), duration_s=(60, 30), rate_mbps=(20, 8)),
}

CLASS_PRIORITY = {"voice": 1, "video": 2, "web": 3, "bulk": 4}  # 1 = highest QoS priority


def generate_flows(n_flows: int, host_pairs, seed=None) -> pd.DataFrame:
    rng = RNG if seed is None else np.random.default_rng(seed)
    rows = []
    for i in range(n_flows):
        cls = rng.choice(TRAFFIC_CLASSES, p=[0.2, 0.25, 0.35, 0.2])
        prof = CLASS_PROFILES[cls]
        pkt_size = max(64, rng.normal(*prof["pkt_size"]))
        iat_ms = max(0.5, rng.normal(*prof["iat_ms"]))
        duration_s = max(0.2, rng.normal(*prof["duration_s"]))
        rate_mbps = max(0.01, rng.normal(*prof["rate_mbps"]))
        src, dst = host_pairs[rng.integers(0, len(host_pairs))]
        n_packets = int((duration_s * 1000) / iat_ms)

        rows.append(dict(
            flow_id=f"f{i}",
            src=src, dst=dst,
            avg_pkt_size=pkt_size,
            avg_iat_ms=iat_ms,
            duration_s=duration_s,
            demand_mbps=rate_mbps,
            n_packets=n_packets,
            true_class=cls,
            priority=CLASS_PRIORITY[cls],
        ))
    return pd.DataFrame(rows)


if __name__ == "__main__":
    from topology import HOST_PAIRS
    df = generate_flows(20, HOST_PAIRS)
    print(df.head())
