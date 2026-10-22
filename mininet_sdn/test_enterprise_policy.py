"""Live packet-forwarding checks for VLAN ACLs (Ubuntu/Mininet, root required)."""

import json
import time

from mininet.log import setLogLevel
from network_topo import build_net
from dashboard_results import save_live_payload


def ping(source, destination):
    output = source.cmd(f"ping -c 2 -W 2 {destination.IP()}")
    return "0% packet loss" in output, output


def http_status(source, address, port):
    code = (
        "import urllib.request; "
        f"print(urllib.request.urlopen('http://{address}:{port}/', timeout=2).status)"
    )
    output = source.cmd("python3 -c \"" + code + "\" 2>&1")
    return "200" in output.splitlines(), output


def main():
    setLogLevel("warning")
    net = build_net(enterprise=True)
    try:
        time.sleep(3)
        web, finance_service = net.get("h9"), net.get("h11")
        web.cmd(f"python3 -m http.server 80 --bind {web.IP()} >/tmp/enterprise_web.log 2>&1 &")
        finance_service.cmd(
            f"python3 -m http.server 8443 --bind {finance_service.IP()} >/tmp/enterprise_finance.log 2>&1 &"
        )
        time.sleep(1)
        cases = []
        branch_web, out = http_status(net.get("h4"), web.IP(), 80)
        cases.append({"name": "branch_to_shared_http", "expected_allowed": True,
                      "connectivity": branch_web, "passed": branch_web, "output": out.strip()})
        finance_http, out = http_status(net.get("h2"), finance_service.IP(), 8443)
        cases.append({"name": "finance_to_finance_service", "expected_allowed": True,
                      "connectivity": finance_http, "passed": finance_http, "output": out.strip()})
        blocked_http, out = http_status(net.get("h4"), finance_service.IP(), 8443)
        cases.append({"name": "branch_to_finance_service_denied", "expected_allowed": False,
                      "connectivity": blocked_http, "passed": not blocked_http, "output": out.strip()})
        for name, source_name, destination_name, expected in [
            ("branch_to_branch_icmp", "h4", "h6", True),
            ("it_to_management", "h3", "h12", True),
            ("finance_to_management_denied", "h2", "h12", False),
        ]:
            ok, output = ping(net.get(source_name), net.get(destination_name))
            cases.append({"name": name, "expected_allowed": expected,
                          "connectivity": ok, "passed": ok == expected,
                          "output": output.strip()})
        results = []
        results.extend(cases)
        payload = {"mode": "mininet_measurement", "results": results,
                   "passed": sum(row["passed"] for row in results), "total": len(results)}
        result_path = save_live_payload("MININET_POLICY", payload, "mininet_policy_latest.json")
        print(json.dumps(payload, indent=2))
        print("Saved live policy measurements to", result_path)
        if payload["passed"] != payload["total"]:
            raise SystemExit("Enterprise ACL integration checks failed")
    finally:
        net.stop()


if __name__ == "__main__":
    main()
