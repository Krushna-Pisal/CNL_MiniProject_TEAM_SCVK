#!/bin/bash
# run_demo.sh
# Brings up Open vSwitch, starts the chosen SDN controller, runs the
# congestion-avoidance demonstration (saturates the s2-s4 link with a bulk
# iperf flow, then opens a new voice-class flow and shows which path the
# controller under test picks for it), and prints the controller's routing
# decisions.
#
# Usage:
#   sudo ./run_demo.sh static      # baseline non-adaptive controller
#   sudo ./run_demo.sh adaptive    # AI-driven adaptive controller
#
# Prerequisites: run once first ->  pip install -r requirements.txt && python3 train_models.py
set -e
cd "$(dirname "$0")"

MODE="$1"
if [[ "$MODE" != "static" && "$MODE" != "adaptive" ]]; then
    echo "Usage: $0 [static|adaptive]"
    exit 1
fi

echo "=== [1/4] starting Open vSwitch ==="
bash start_ovs.sh

echo "=== [2/4] cleaning up any previous Mininet state ==="
mn -c > /dev/null 2>&1 || true

echo "=== [3/4] starting controller_${MODE}.py ==="
rm -f controller_${MODE}.log
python3 osken_run.py controller_${MODE} > controller_${MODE}.log 2>&1 &
CTRL_PID=$!
sleep 3
if ! ss -tln 2>/dev/null | grep -q 6653; then
    echo "Controller failed to start -- see controller_${MODE}.log"
    cat controller_${MODE}.log
    exit 1
fi
echo "controller running (pid $CTRL_PID), listening on 6653"

echo "=== [4/4] running congestion-avoidance test ==="
python3 test_congestion_avoidance.py

kill -9 "$CTRL_PID" 2>/dev/null || true

echo ""
echo "=== ${MODE} controller's routing decisions for this run ==="
grep -E "\[${MODE}\]" "controller_${MODE}.log" || true
