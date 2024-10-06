#!/bin/bash

poetry install

# Flush/delete all existing rules
iptables -F
iptables -t mangle -F
iptables -X

# Accept everything by default
iptables -P INPUT ACCEPT
iptables -P OUTPUT ACCEPT
iptables -P FORWARD ACCEPT


# Based on: https://www.kernel.org/doc/html/v5.12/networking/tproxy.html
iptables -t mangle -N DIVERT
iptables -t mangle -A PREROUTING -p tcp -m socket -j DIVERT
iptables -t mangle -A DIVERT -j MARK --set-mark 1
iptables -t mangle -A DIVERT -j ACCEPT

ip rule add fwmark 1 lookup 100
ip route add local 0.0.0.0/0 dev lo table 100

# Set up TPROXY
iptables -t mangle -A PREROUTING -s 10.5.0.6 -d 192.0.2.123 -p tcp -j TPROXY --tproxy-mark 0x1/0x1 --on-port 1234
iptables -t mangle -A PREROUTING -s 10.5.0.6 -d 192.0.2.123 -p udp -j TPROXY --tproxy-mark 0x1/0x1 --on-port 1235

# Forward all other traffic by the OpenVAS-Scanner container
iptables -t nat -A POSTROUTING -s 10.5.0.6 -j MASQUERADE

sleep infinity
