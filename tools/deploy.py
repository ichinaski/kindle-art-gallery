#!/usr/bin/env python3
"""Install the art gallery on the Kindle over SSH (it must be awake, SSH enabled).

  uv run --with paramiko python tools/deploy.py           app + library items + boot hook
  uv run --with paramiko python tools/deploy.py --admin   also show the admin items (SSH,
                                                          autostart) in the library
  uv run --with paramiko python tools/deploy.py --dev     also the probes (art/dev)
  uv run --with paramiko python tools/deploy.py --content also content/ (catalogue, panels)
  uv run --with paramiko python tools/deploy.py --fonts   also the fonts

The library normally shows only the owner's two items (gallery, update); the admin
items are kept in art/admin/ on the device, out of the library, and --admin copies them
into the library too. Also blocks Amazon's firmware updates (update.bin.tmp.partial),
which would undo the jailbreak. Config, calibration and state are never overwritten. --content also
removes panels that are no longer in the catalogue.
"""
import argparse, os, sys, paramiko

HOST = os.environ.get("KINDLE_HOST") or sys.exit("Set KINDLE_HOST to the Kindle's IP address (Settings, Wi-Fi, or your router).")
ART = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "art")
D = "/mnt/us/art"

APP = ["artd.lua", "widths.lua", "gallery.sh", "ui.sh", "start-art.sh", "stop-art.sh", "artsync.sh", "bin/evtap"]
DOCS = ["doc/Start-Art-Gallery.sh", "doc/Update-Gallery.sh"]  # the library, for the owner
ADMIN = ["doc/Toggle-Autostart.sh", "doc/Enable-SSH.sh"]         # art/admin/; --admin: library
DEV = ["dev/probe-touch.sh", "dev/probe-power.sh", "dev/probe-sleep.sh"]
DEV_DOCS = ["dev/doc/Probe-Touch.sh", "dev/doc/Probe-Power.sh", "dev/doc/Probe-Sleep.sh"]

p = argparse.ArgumentParser()
p.add_argument("--dev", action="store_true")
p.add_argument("--content", action="store_true")
p.add_argument("--fonts", action="store_true")
p.add_argument("--admin", action="store_true")
a = p.parse_args()

files = [(f, f"{D}/{f}") for f in APP]
files += [(f, f"/mnt/us/documents/{os.path.basename(f)}") for f in DOCS]
files += [(f, f"{D}/admin/{os.path.basename(f)}") for f in ADMIN]
if a.admin:
    files += [(f, f"/mnt/us/documents/{os.path.basename(f)}") for f in ADMIN]
files += [("emergency.sh", "/mnt/us/emergency.sh")]
if a.dev:
    files += [(f, f"{D}/{os.path.basename(f)}") for f in DEV]
    files += [(f, f"/mnt/us/documents/{os.path.basename(f)}") for f in DEV_DOCS]
dirs = {f"{D}/bin", f"{D}/fonts", f"{D}/admin", f"{D}/content/images",
        "/mnt/us/update.bin.tmp.partial"}  # a directory here blocks OTA downloads
if a.content:
    content = os.path.join(ART, "..", "content")
    files += [(os.path.join("..", "content", f), f"{D}/content/{f}") for f in ("catalog.tsv", "collections.tsv")]
    for line in open(os.path.join(content, "catalog.tsv")):
        if line.startswith("#"):
            continue
        rel = line.split("\t")[2]  # <collection>/<id>.png
        files.append((os.path.join("..", "content", "panels", rel), f"{D}/content/images/{rel}"))
        dirs.add(f"{D}/content/images/{rel.split('/')[0]}")
if a.fonts:
    files += [(f"assets/fonts/{f}", f"{D}/fonts/{f}") for f in
              ("AtkinsonHyperlegible-Regular.ttf", "AtkinsonHyperlegible-Bold.ttf")]

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(HOST, username="root", password=os.environ.get("KINDLE_PASS", "kindle"), timeout=20, banner_timeout=60,
          auth_timeout=60, look_for_keys=False, allow_agent=False)
c.exec_command("mkdir -p " + " ".join(sorted(dirs)))[1].channel.recv_exit_status()
s = c.open_sftp()
if a.content:
    # skip panels the device already has with the same sha256 (catalogue column 4)
    have = {}
    out = c.exec_command(f"cd {D}/content/images && sha256sum */*.png 2>/dev/null")[1].read().decode()
    for line in out.splitlines():
        h, _, rel = line.partition("  ")
        have[f"{D}/content/images/{rel}"] = h
    want = {f"{D}/content/images/{l.split(chr(9))[2]}": l.split(chr(9))[3]
            for l in open(os.path.join(content, "catalog.tsv")) if not l.startswith("#")}
    before = len(files)
    files = [(l, r) for l, r in files if not (r in want and have.get(r) == want[r])]
    print(f"  {before - len(files)} panels already up to date")
for local, remote in files:
    s.put(os.path.join(ART, local), remote)
    s.chmod(remote, 0o755)
    print(f"  {local} -> {remote}")
if not a.admin:
    for f in ADMIN:  # out of the library
        try:
            s.remove(f"/mnt/us/documents/{os.path.basename(f)}")
            print(f"  removed from the library: {os.path.basename(f)}")
        except IOError:
            pass
if a.content:
    # panels no longer in the catalogue (rejected works, removed collections)
    keep = {f"{D}/content/images/{l.split(chr(9))[2]}"
            for l in open(os.path.join(content, "catalog.tsv")) if not l.startswith("#")}
    out = c.exec_command(f"find {D}/content/images -type f")[1].read().decode().split("\n")
    for f in sorted(set(filter(None, out)) - keep):
        s.remove(f)
        print(f"  removed {f}")
    c.exec_command(f"for d in {D}/content/images/*/; do rmdir \"$d\" 2>/dev/null; done")[1].channel.recv_exit_status()
s.close()
c.close()
print(f"{len(files)} files installed")
