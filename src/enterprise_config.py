"""Shared enterprise VLAN, host, service, and access policy configuration.

This module is consumed by the graph simulation and, through the Mininet
configuration generator, by the OpenFlow controllers. Host VLANs are access
VLANs; all inter-switch links are trunks.
"""

from __future__ import annotations

from typing import Any

VLAN_SEGMENTS = {
    10: {"name": "Administration", "subnet": "10.10.10.0/24", "gateway": "10.10.10.1"},
    20: {"name": "Finance", "subnet": "10.10.20.0/24", "gateway": "10.10.20.1"},
    30: {"name": "IT", "subnet": "10.10.30.0/24", "gateway": "10.10.30.1"},
    40: {"name": "Branch 1 users", "subnet": "10.10.40.0/24", "gateway": "10.10.40.1"},
    41: {"name": "Branch 2 users", "subnet": "10.10.41.0/24", "gateway": "10.10.41.1"},
    50: {"name": "Shared services", "subnet": "10.10.50.0/24", "gateway": "10.10.50.1"},
    99: {"name": "Management", "subnet": "10.10.99.0/24", "gateway": "10.10.99.1"},
}

# name, switch, VLAN, host number, role
_HOST_ROWS = [
    ("h1", "s1", 10, 10, "admin"),
    ("h2", "s2", 20, 10, "finance"),
    ("h3", "s3", 30, 10, "it"),
    ("h4", "s5", 40, 10, "branch1"),
    ("h5", "s7", 40, 11, "branch1"),
    ("h6", "s8", 41, 10, "branch2"),
    ("h7", "s6", 41, 11, "branch2"),
    ("h8", "s4", 50, 10, "dns"),
    ("h9", "s4", 50, 11, "web"),
    ("h10", "s2", 50, 12, "files"),
    ("h11", "s2", 50, 13, "finance_service"),
    ("h12", "s1", 99, 10, "management"),
    ("h13", "s5", 40, 12, "branch1"),
    ("h14", "s8", 41, 12, "branch2"),
]

HOSTS = {
    name: {
        "name": name,
        "switch": switch,
        "vlan": vlan,
        "subnet": VLAN_SEGMENTS[vlan]["subnet"],
        "gateway": VLAN_SEGMENTS[vlan]["gateway"],
        "ip": f"10.10.{vlan}.{host_num}",
        "role": role,
        "site": ("Headquarters" if switch in {"s1", "s2", "s3", "s4"}
                 else "Branch Office 1" if switch in {"s5", "s7"}
                 else "Branch Office 2"),
    }
    for name, switch, vlan, host_num, role in _HOST_ROWS
}

GATEWAY_MAC = "02:00:00:00:00:01"


def policy_allows(src: dict[str, Any], dst: dict[str, Any], protocol: str,
                  dst_port: int, src_port: int = 0) -> bool:
    """Default-deny inter-VLAN policy for internal enterprise flows.

    Same-segment traffic is permitted, except management access is limited
    to administrators and IT. Cross-segment services are allow-listed by
    protocol and destination port. `protocol` is one of tcp/udp/icmp/other.
    """
    src_role, dst_role = src.get("role"), dst.get("role")
    src_vlan, dst_vlan = src.get("vlan"), dst.get("vlan")

    # Permit responses from explicitly authorized services. This is a
    # stateless return-path allowance; it is deliberately limited by source
    # role and service port rather than opening arbitrary reverse traffic.
    if src_role == "management":
        return dst_role in {"admin", "it"} and (
            protocol == "icmp" or (protocol == "tcp" and src_port == 22)
        )
    if src_role == "dns":
        return dst_role in {"admin", "finance", "it", "branch1", "branch2"} and protocol in {"tcp", "udp"} and src_port == 53
    if src_role == "web":
        return dst_role in {"admin", "finance", "branch1", "branch2"} and protocol == "tcp" and src_port in {80, 443}
    if src_role == "files":
        return dst_role in {"admin", "finance"} and protocol == "tcp" and src_port == 21
    if src_role == "finance_service":
        return dst_role in {"admin", "finance"} and protocol == "tcp" and src_port == 8443

    if dst_role == "management":
        return src_role in {"admin", "it"} and protocol in {"tcp", "udp", "icmp"}
    if src_role == "it":
        return True
    if src_vlan == dst_vlan:
        return True
    if dst_role == "dns":
        return protocol in {"tcp", "udp"} and dst_port == 53
    if dst_role == "web":
        return protocol == "tcp" and dst_port in {80, 443}
    if dst_role == "files":
        return src_role in {"admin", "finance"} and protocol == "tcp" and dst_port == 21
    if dst_role == "finance_service":
        return src_role in {"admin", "finance"} and protocol == "tcp" and dst_port == 8443
    if src_role == "admin":
        return True
    if src_role in {"branch1", "branch2"} and dst.get("role") in {"branch1", "branch2"}:
        return protocol == "icmp"
    return False

