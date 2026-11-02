# Development

## Workflow

```
python3 art/sim/sim.py                                     desktop tests (fake fbink and evtap)
uv run --with paramiko python tools/deploy.py              app, library items, boot hook
uv run --with paramiko python tools/deploy.py --content    also the catalogue and panels
uv run --with paramiko python tools/deploy.py --admin      also the admin library items
uv run --with paramiko python tools/deploy.py --dev        also the probes (art/dev)
uv run --with paramiko python tools/kexec.py '<command>'   run a command on the Kindle
uv run --with fonttools python tools/fontwidths.py         art/widths.lua, after font changes
uv run --with pillow python tools/screenshots.py           the README pictures
```

The tools read the Kindle's address from `KINDLE_HOST` (and `KINDLE_PASS`, default
`kindle`). SSH only works while the Kindle is awake, and is off after every restart
until "9. Enable SSH (Wi-Fi)" runs.

The simulator runs `artd.lua` against scripted touch scenarios, with fake `fbink` and
`evtap` and a simulated clock. Run it on Lua 5.1, the Kindle's version, after every
change to `artd.lua`: `LUA=/path/to/lua5.1 python3 art/sim/sim.py` (one way to get it:
`uv run --with hererocks hererocks -l 5.1 /tmp/lua51`).

**The running gallery turns Wi-Fi off** (`WIFI=0`), so an SSH session that starts it
dies a few seconds later and its output is lost. Start it at the end of a command, then
leave the gallery to get SSH back (power button, **Ajustes**, **Salir de la galería**,
**Sí, salir**; leaving restores Wi-Fi), or hold two fingers on the screen for 2 s. For
long sessions, set `WIFI=1` and create `/mnt/us/art/stay-awake`, and undo both after.

`art/evtap` is committed as a static soft-float ARM binary; rebuild it with
`sh art/evtap/build.sh` (zig from PyPI) only if `evtap.c` changes.

## Device facts (Kindle Paperwhite 4)

| Item | Value |
| --- | --- |
| Firmware | 5.18.1, jailbroken with SpiderCat; works unregistered |
| Screen | 1072x1448 portrait, 16 grey levels, 300 dpi, 9.1 x 12.3 cm visible |
| Landscape | 1448x1072 with `/sys/class/graphics/fb0/rotate` = 0 (the Kindle UI uses 3) |
| Lua | 5.1.4 at `/usr/bin/lua` |
| Drawing | FBInk 1.25 at `/mnt/us/libkh/bin/fbink` (`-e` crashes on this build) |
| Touchscreen | goodix `gt9xx-ts`, `/dev/input/event2`, multitouch type B, 16 slots |
| Power keys | `/dev/input/event0` (snvs) and `/dev/input/event1` (bd71827 PMIC) |
| Frontlight | `/sys/class/backlight/bl/brightness`, 0 to 2047 |
| Clock/wake | `/dev/rtc0` (bd71827); enable with `/sys/class/rtc/rtc0/device/power/wakeup` |
| Battery | about 1530 mAh; `gasgauge-info -c` (%) and `-m` (µAh, coarse) |
| User storage | `/mnt/us`, a FUSE mount over `/mnt/base-us`, 6.2 GB |
| Network | curl 7.86 with OpenSSL 1.0.2q reaches GitHub over HTTPS; busybox has `sha256sum` |

## How the gallery works

**Pause, don't stop.** `gallery.sh` freezes the Kindle UI (`SIGSTOP` on `cvm` and
`awesome`), hides the status bar and blocks the screen saver; X keeps running. On exit,
for any reason, it restores the framebuffer rotation, frontlight and Wi-Fi, sends
`SIGCONT`, and opens the library. This is how KOReader runs alongside the Kindle UI,
and it makes leaving instant.

**Runs from RAM.** `start-art.sh` copies the program to `/tmp/art-run` and runs it from
there, with logs in `/tmp`. Connecting the Kindle to a computer takes `/mnt/us` away (USB
drive mode); the gallery keeps the current picture until it comes back.

**Input.** `evtap` grabs the touchscreen and the power keys with `EVIOCGRAB`, so the
paused UI and powerd never see them, and streams their events plus a 250 ms heartbeat to
`artd.lua`, where one loop handles touches and timers. The touchscreen reports portrait
coordinates already calibrated by its controller, so landscape is a fixed rotation (x =
raw y, y = 1071 - raw x); a `calibration` file with an affine map overrides it if a
device ever needs one.

**Sleep and battery.** Awake, the Kindle draws about 30 mA whatever the app does, so
the gallery suspends to RAM (`rtcwake -m mem`) after 30 s without touches until the next
change. The frontlight goes to 0 before every sleep and comes back on interaction.
Measured with hourly changes: about 2.9 mA on average, three weeks per charge, nearly
all of it the Kindle's own suspend current. The gallery never lets powerd's screensaver
or its deeper hibernation (`SUSPEND_TO_DISK`) kick in; driving hibernation ourselves
would only pay off for long sleeps.

**Text.** The bar measures text with the fonts' advance widths (`art/widths.lua`) and
shrinks it to fit rather than cutting titles. Each new painting checks the battery: at
15% or less a badge is drawn over it, at 5% or less a charge screen replaces it.

**Autostart.** The jailbreak's `/etc/upstart/kmc.conf` runs `/mnt/us/emergency.sh` on
every boot once the Kindle UI is ready. Ours starts the gallery 45 s later, unless
`/mnt/us/art/no-autostart` exists.

## Traps already found

- Anything that pauses the Kindle UI must resume it whatever happens. Run such scripts
  detached (`setsid`) with a dead-man's switch: a hung test once left the UI frozen and
  needed a forced restart. The probes in `art/dev` do this.
- `pkill -f <name>` over SSH matches the SSH command itself and kills it.
- A `reboot` backgrounded in an SSH command dies with the session; restart from the
  Kindle's settings instead.
- `/mnt/us` disappears in USB drive mode; files there (like `stay-awake`) vanish
  meanwhile. Charging from a wall plug is fine.
- Deregistering the Kindle empties `/mnt/us/documents` (library items).
- The touchscreen only reports coordinates that change, even across touches: `evtap`
  sends the current slot positions at start and `artd.lua` keeps them between touches.
  Do not reset them per touch.
- FBInk's `-e` (print state) segfaults on this build; `-m -p` (centred, padded to the
  line) is the way to overwrite a message line.
- The battery gauge (`gasgauge-info -m`) re-estimates at rest; only trust trends over
  many hours.
- A dropped Wi-Fi connection during `deploy.py --content` can leave a truncated panel.
  `artsync.sh` repairs it, since it compares the actual files' sha256.
