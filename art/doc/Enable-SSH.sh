#!/bin/sh
# Name: 9. Enable SSH (Wi-Fi)
# Author: art
# Start the SSH server the way Jobman does (root, password "kindle"), and open port
# 22 in the firewall (its rules reset on every restart). Needed after every restart.
# Replaces the Jobman launcher removed by deregistering.
FBINK=/mnt/us/libkh/bin/fbink
iptables -L INPUT -n 2>/dev/null | grep -q "tcp dpt:22$" ||
  iptables -I INPUT -p tcp --dport 22 -j ACCEPT
lipc-set-prop com.lab126.cmd wirelessEnable 1 >/dev/null 2>&1
if pidof dropbearmulti >/dev/null 2>&1; then
  $FBINK -q -m -y -5 "SSH ya esta activo"
else
  setsid /mnt/us/jobman/bin/dropbearmulti dropbear -R -H/mnt/us -p22 -Ykindle </dev/null >/dev/null 2>&1
  $FBINK -q -m -y -5 "SSH activado"
fi
