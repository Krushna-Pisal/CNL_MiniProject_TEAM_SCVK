#!/bin/bash
# Enterprise Mininet demo with policy checks and a measured failover cycle.
# Usage: sudo ./run_enterprise_demo.sh [static|adaptive]
set -euo pipefail
cd "$(dirname "$0")"
MODE="${1:-adaptive}"
if [[ "$MODE" != "static" && "$MODE" != "adaptive" ]]; then
  echo "Usage: $0 [static|adaptive]"
  exit 1
fi

bash start_ovs.sh
mn -c >/dev/null 2>&1 || true

# Generate actual Mininet port numbers before the controller loads its graph.
python3 network_topo.py --enterprise --no-cli

export SDN_ENTERPRISE=1
export SDN_CONTROLLER_LOG="controller_enterprise.log"
rm -f "$SDN_CONTROLLER_LOG"
python3 -u osken_run.py "controller_${MODE}" >"$SDN_CONTROLLER_LOG" 2>&1 &
CTRL_PID=$!
cleanup() {
  kill "$CTRL_PID" 2>/dev/null || true
}
trap cleanup EXIT
sleep 3
if ! ss -tln 2>/dev/null | grep -q 6653; then
  echo "Controller failed to start; see $SDN_CONTROLLER_LOG"
  cat "$SDN_CONTROLLER_LOG"
  exit 1
fi

python3 test_enterprise_policy.py
python3 test_enterprise_failover.py
echo "Controller events: $SDN_CONTROLLER_LOG"
