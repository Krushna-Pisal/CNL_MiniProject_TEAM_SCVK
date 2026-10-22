#!/bin/bash
# start_ovs.sh
# Starts Open vSwitch daemons manually. Needed on systems without systemd
# (e.g. minimal containers/VMs); on a normal Ubuntu install you can instead
# just use `service openvswitch-switch start`.
set -e

mkdir -p /var/run/openvswitch /var/log/openvswitch /etc/openvswitch

if ! ovs-vsctl show > /dev/null 2>&1; then
    [ -f /etc/openvswitch/conf.db ] || \
        ovsdb-tool create /etc/openvswitch/conf.db /usr/share/openvswitch/vswitch.ovsschema
    ovsdb-server --remote=punix:/var/run/openvswitch/db.sock \
        --remote=db:Open_vSwitch,Open_vSwitch,manager_options \
        --pidfile --detach --log-file
    sleep 1
    ovs-vsctl --no-wait init
    ovs-vswitchd --pidfile --detach --log-file
    sleep 1
fi

echo "Open vSwitch is up:"
ovs-vsctl show
