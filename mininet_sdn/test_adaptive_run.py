from network_topo import build_net
from mininet.log import setLogLevel
import time

setLogLevel('info')
net = build_net()
time.sleep(2)

pairs = [("h1", "h6"), ("h2", "h5"), ("h3", "h4")]
for a, b in pairs:
    ha, hb = net.get(a), net.get(b)
    out = ha.cmd(f"ping -c 2 -W 2 {hb.IP()}")
    ok = "0% packet loss" in out
    print(f"=== {a} -> {b}: {'OK' if ok else 'FAIL'} ===")
    print(out)

net.stop()
