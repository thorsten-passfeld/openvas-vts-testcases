#!/bin/bash

ip route del default

# The default gateway is the recorder container
ip route add default via 10.5.0.5 dev eth0

sleep infinity
