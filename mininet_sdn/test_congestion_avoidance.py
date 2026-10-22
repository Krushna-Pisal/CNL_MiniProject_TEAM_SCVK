"""
test_congestion_avoidance.py
The real demonstration: saturates the s2-s4 link (shared bottleneck on the
shortest path from h2 to both h4 and h5) with a long bulk-class iperf
transfer, then opens a new voice-class flow from h2 -> h5 while that
congestion is happening, and shows which path the controller under test
chose for it.

Usage:
    python3 test_congestion_avoidance.py
(run once with controller_static.py listening, once with
controller_adaptive.py listening -- see run_congestion_demo.sh)
"""
import time
import sys
from network_topo import build_net
from mininet.log import setLogLevel

setLogLevel('info')
net = build_net()
time.sleep(2)

h2, h4, h5 = net.get('h2'), net.get('h4'), net.get('h5')

print("*** starting bulk iperf server on h4 (port 5001)")
h4.cmd('iperf -s -u -p 5001 > /tmp/iperf_server.log 2>&1 &')
time.sleep(1)

print("*** starting bulk iperf CLIENT h2 -> h4 (60 Mbps UDP, saturates s2-s4)")
h2.cmd(f'iperf -c {h4.IP()} -u -p 5001 -b 60M -t 12 > /tmp/iperf_client.log 2>&1 &')

print("*** letting bulk flow run for 6s so port-stats polling picks it up")
time.sleep(6)

print("*** opening a NEW voice-class flow h2 -> h5 (UDP port 5060) while h2->h4 is congested")
h2.cmd(f'python3 -c "import socket; s=socket.socket(socket.AF_INET, socket.SOCK_DGRAM); '
       f's.sendto(b\'voice-test-packet\', (\'{h5.IP()}\', 5060))"')

time.sleep(2)
print("*** done -- check the controller log for the path chosen for 10.0.0.2 -> 10.0.0.5")

net.stop()
