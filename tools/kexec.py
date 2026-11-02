#!/usr/bin/env python3
"""Run a command on the Kindle over SSH (password auth), for development.

usage: kexec.py 'uname -a'      |  kexec.py --file script.sh  |  kexec.py -  (stdin)
"""
import argparse, os, sys, paramiko

HOST = os.environ.get("KINDLE_HOST") or sys.exit("Set KINDLE_HOST to the Kindle's IP address (Settings, Wi-Fi, or your router).")
USER = os.environ.get("KINDLE_USER", "root")
PASS = os.environ.get("KINDLE_PASS", "kindle")

p = argparse.ArgumentParser()
p.add_argument("command", nargs="?", help="command to run")
p.add_argument("--file", help="run this local script")
p.add_argument("--put", action="append", default=[], metavar="LOCAL:REMOTE",
               help="upload a file (repeatable)")
p.add_argument("--timeout", type=float, default=120)
p.add_argument("--wait", type=float, default=0,
               help="keep trying to connect for this many seconds (the device sleeps most of the time)")
a = p.parse_args()

if a.file:
    cmd = open(a.file).read()
elif a.put and not a.command:
    cmd = "true"
elif a.command == "-" or (a.command is None and not sys.stdin.isatty()):
    cmd = sys.stdin.read()
else:
    cmd = a.command

import time
deadline = time.time() + a.wait
attempt = 0
while True:
    attempt += 1
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        c.connect(HOST, username=USER, password=PASS,
                  timeout=float(os.environ.get("KINDLE_TIMEOUT", 20)),
                  banner_timeout=60, auth_timeout=60, look_for_keys=False, allow_agent=False)
        break
    except Exception as e:
        if time.time() >= deadline:
            print(f"gave up after {attempt} attempts: {type(e).__name__}: {e}")
            raise SystemExit(1)
        c.close()
        time.sleep(0.7)
if a.put:
    sftp = c.open_sftp()
    for spec in a.put:
        local, remote = spec.split(":", 1)
        sftp.put(local, remote)
        sftp.chmod(remote, 0o755)
        print(f"uploaded {local} -> {remote}")
    sftp.close()

stdin, stdout, stderr = c.exec_command(cmd, timeout=a.timeout)
out = stdout.read().decode(errors="replace")
err = stderr.read().decode(errors="replace")
rc = stdout.channel.recv_exit_status()
sys.stdout.write(out)
if err.strip():
    sys.stderr.write("--- stderr ---\n" + err)
print(f"--- exit {rc}")
c.close()
