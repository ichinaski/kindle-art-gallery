#!/usr/bin/env python3
"""Run artd.lua on the desktop against scripted touch scenarios.

Fakes fbink (logs the calls) and evtap (plays a scenario as raw input_event
records, with heartbeats as the clock: 4 heartbeats = 1 simulated second).
The touchscreen is simulated like the PW4's: portrait panel coordinates, rotated
into landscape (raw x = 1071 - y, raw y = x).

  python3 art/sim/sim.py          run every scenario, print pass/fail
"""

import os
import shutil
import struct
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ARTD = os.path.join(HERE, "..", "artd.lua")
LUA = os.environ.get("LUA", "lua")
W, H = 1448, 1072

EV_SYN, EV_KEY, EV_ABS = 0, 1, 3
SLOT, MTX, MTY, TRACK = 0x2F, 0x35, 0x36, 0x39


def raw(x, y):
    """Logical landscape pixel -> raw portrait touch coordinate (as on the PW4)."""
    return H - 1 - y, x


def rec(t, c, v):
    return struct.pack("<IIHHi", 0, 0, t, c, v)


HB = b"\xff" * 16


class Scenario:
    def __init__(self, lifts=True):
        self.out = bytearray()
        self.lifts = lifts
        self.track = 1
        self.last = {}  # slot -> (rx, ry): like the kernel, only send what changed

    def wait(self, secs):
        self.out += HB * int(secs * 4)
        return self

    def _pos(self, x, y, slot=0):
        rx, ry = raw(x, y)
        lx, ly = self.last.get(slot, (None, None))
        self.out += rec(EV_ABS, SLOT, slot)
        if rx != lx:
            self.out += rec(EV_ABS, MTX, rx)
        if ry != ly:
            self.out += rec(EV_ABS, MTY, ry)
        self.out += rec(EV_SYN, 0, 0)
        self.last[slot] = (rx, ry)

    def _down(self, slot=0):
        self.out += rec(EV_ABS, SLOT, slot) + rec(EV_ABS, TRACK, self.track)
        self.track += 1

    def _up(self, slot=0):
        if self.lifts:
            self.out += rec(EV_ABS, SLOT, slot) + rec(EV_ABS, TRACK, -1) + rec(EV_SYN, 0, 0)
        else:
            self.wait(1)  # the panel goes silent; artd must infer the lift

    def tap(self, x, y):
        self._down()
        self._pos(x, y)
        self.wait(0.25)
        self._up()
        return self.wait(0.5)

    def swipe(self, x0, y0, x1, y1):
        self._down()
        for i in range(6):
            self._pos(x0 + (x1 - x0) * i // 5, y0 + (y1 - y0) * i // 5)
            self.wait(0.25 if i == 5 else 0)
        self._up()
        return self.wait(0.5)

    def power(self):
        self.out += rec(EV_KEY, 116, 1) + rec(EV_SYN, 0, 0) + rec(EV_KEY, 116, 0) + rec(EV_SYN, 0, 0)
        return self.wait(0.5)

    def two_finger_hold(self, secs):
        self._down(0)
        self._pos(500, 500, 0)
        self._down(1)
        self._pos(900, 500, 1)
        self.wait(secs)  # still fingers: no events at all
        if self.lifts:
            self._up(1)
            self._up(0)
        return self.wait(0.5)


FAKE_FBINK = """#!/bin/sh
echo "$*" >>"$ART_DIR/fbink.log"
case "$*" in *" -v"*|"-v") echo "Variable fb info: 1448x1072" >&2;; esac
"""

FAKE_EVTAP = """#!/bin/sh
cat "$ART_DIR/scenario.bin"
"""


def bar_button(name):
    xs = {"prev": 24 + 60, "next": 160 + 60, "settings": W - 24 - 150}
    return xs[name], H - 300 + 186 + 48


# Ajustes and the exit confirmation (centres of the targets, as laid out in artd.lua)
SETTINGS = {
    "coll1": (60 + 300, 150 + 40), "coll2": (760 + 300, 150 + 40),
    "1h": (400 + 164 + 75, 742 + 40), "exit": (60 + 240, 980), "done": (W - 60 - 200, 980),
    "stay": (214 + 250, 690 + 60), "leave": (734 + 250, 690 + 60),
}


def exit_taps(s, mirror=False):
    """Open the bar, then Ajustes, Salir, Sí: the only way out besides the failsafe."""
    pts = [(700, 400), bar_button("settings"), SETTINGS["exit"], SETTINGS["leave"]]
    for x, y in pts:
        s.tap(W - 1 - x if mirror else x, y)
    return s


def run(name, scenario, config="INTERVAL=60\nROT=0\nSLEEP=0\n", calibration=None, n=5, images=True,
        content=None, shuffle=False, env=None, title=None):
    d = tempfile.mkdtemp(prefix="artsim-")
    os.makedirs(os.path.join(d, "images"))
    with open(os.path.join(d, "manifest.tsv"), "w") as fh:
        for i in range(1, n + 1):
            fh.write(f"{i:03d}.png\t{title or f'Title {i}'}\tArtist {i}\t19{i:02d}\n")
            if images:
                open(os.path.join(d, "images", f"{i:03d}.png"), "wb").write(b"png")
    if content:  # {collection: count}: the content/ layout with a catalogue
        os.makedirs(os.path.join(d, "content", "images"))
        with open(os.path.join(d, "content", "collections.tsv"), "w") as fh:
            fh.write("# id\tname\torder\n")
            for k, cid in enumerate(content):
                fh.write(f"{cid}\t{cid.title()}\t{k}\n")
        with open(os.path.join(d, "content", "catalog.tsv"), "w") as fh:
            fh.write("# id\tcollection\tfile\tsha256\ttitle\tartist\tdate\n")
            for cid, count in content.items():
                os.makedirs(os.path.join(d, "content", "images", cid))
                for i in range(1, count + 1):
                    open(os.path.join(d, "content", "images", cid, f"w{i}.png"), "wb").write(b"png")
                    fh.write(f"{cid}-{i}\t{cid}\t{cid}/w{i}.png\t-\t{cid.title()} {i}\tArtist\t1650\n")
    with open(os.path.join(d, "config"), "w") as fh:
        fh.write(config)
    if calibration:
        with open(os.path.join(d, "calibration"), "w") as fh:
            fh.write(calibration)
    for fname, body in (("fbink", FAKE_FBINK), ("evtap", FAKE_EVTAP)):
        p = os.path.join(d, fname)
        with open(p, "w") as fh:
            fh.write(body)
        os.chmod(p, 0o755)
    os.makedirs(os.path.join(d, "backlight"))
    for f, v in (("brightness", "800\n"), ("max_brightness", "2047\n")):
        with open(os.path.join(d, "backlight", f), "w") as fh:
            fh.write(v)
    with open(os.path.join(d, "scenario.bin"), "wb") as fh:
        fh.write(scenario.out)
    env = dict(os.environ, ART_SIM="1", ART_DIR=d, ART_NOSHUFFLE="0" if shuffle else "1", ART_FBINK=os.path.join(d, "fbink"),
               ART_EVTAP=os.path.join(d, "evtap"), ART_FB_ROTATE=os.path.join(d, "fb_rotate"),
               ART_BACKLIGHT=os.path.join(d, "backlight"), **(env or {}))
    proc = subprocess.run([LUA, ARTD], env=env, capture_output=True, text=True, timeout=60)
    read = lambda f: open(os.path.join(d, f)).read() if os.path.exists(os.path.join(d, f)) else ""
    result = {"dir": d, "code": proc.returncode, "stderr": proc.stderr, "log": read("artd.log"),
              "fbink": read("fbink.log"), "config": read("config"), "state": read("state"),
              "calibration": read("calibration"), "light": read("backlight/brightness").strip()}
    return result


def check(name, res, *conds):
    failed = [label for label, ok in conds if not ok]
    status = "PASS" if not failed else "FAIL"
    print(f"{status} {name}")
    for label in failed:
        print(f"   - {label}")
    if failed:
        print("   log:\n" + "\n".join("     " + l for l in res["log"].splitlines()[-25:]))
        if res["stderr"]:
            print("   stderr: " + res["stderr"])
    else:
        shutil.rmtree(res["dir"])
    return not failed


def stop_reason(res):
    for line in res["log"].splitlines():
        if " stopping: " in line:
            return line.split(" stopping: ", 1)[1]
    return None


def main():
    ok = True
    sx, sy = bar_button("settings")
    nx, ny = bar_button("next")

    # 1. first start: no calibration screen, built-in mapping; tap -> bar -> exit
    s = exit_taps(Scenario().wait(1)).wait(2)
    r = run("first", s)
    ok &= check("first start, built-in touch map, exit through Ajustes", r,
                ("exits cleanly", r["code"] == 0),
                ("stops via exit button", stop_reason(r) == "exit button"),
                ("asked first", "¿Salir de la galería?" in r["fbink"]),
                ("bar shows battery", "Batería 77%" in r["fbink"]),
                ("rotation probe finds landscape", "rotation 0 -> 1448x1072" in r["log"]))

    # 1b. a calibration file overrides the built-in map (here: an x mirror)
    mirror = f"a=0\nb=-1\nc={W - 1}\nd=-1\ne=0\nf={H - 1}\n"
    s = exit_taps(Scenario().wait(1), mirror=True).wait(2)
    r = run("override", s, calibration=mirror)
    ok &= check("calibration file overrides the built-in map", r,
                ("uses the file", "using the calibration file" in r["log"]),
                ("mirrored taps hit Exit", stop_reason(r) == "exit button"))

    # 2. swipes, interval button, bar closes on a tap above it, auto advance
    s = (Scenario().wait(1)
         .swipe(1100, 500, 300, 500)      # left: next -> index 1
         .swipe(300, 500, 1100, 500)      # right: previous -> index 0
         .swipe(1100, 500, 300, 500)      # next -> index 1
         .tap(700, 400)                   # open bar
         .tap(nx, ny)                     # next button -> index 2
         .tap(700, 300)                   # close bar
         .tap(700, 400)                   # open it again
         .tap(sx, sy)                     # Ajustes
         .tap(*SETTINGS["1h"])            # interval 60 -> 3600
         .tap(*SETTINGS["done"])          # back to the painting
         .wait(5))
    r = run("navigate", s)
    ok &= check("swipes, next button, close bar, interval in Ajustes", r,
                ("ends with the input stream", stop_reason(r) == "input stream ended"),
                ("third work saved", "pos=3\n" in r["state"]),
                ("interval now 1 hour", "INTERVAL=3600" in r["config"]),
                ("settings shown", "settings shown" in r["log"]),
                ("interval options drawn", " 1 h" in r["fbink"] and "Cambiar cada" in r["fbink"]))

    # 3. automatic change after the interval, but not while the bar is open
    s = Scenario().wait(61).tap(700, 400).wait(50).tap(700, 300).wait(61)
    r = run("auto", s)
    shows = r["log"].count("showing ")
    ok &= check("automatic refresh every INTERVAL", r,
                ("first change after 60 s", "showing 2/5" in r["log"]),
                ("no change while the bar is open, then one after", "pos=3\n" in r["state"]),
                ("expected number of redraws", shows == 4))

    # 4. two-finger hold exits, from the image or with the bar open
    s = Scenario().wait(1).tap(700, 400).two_finger_hold(2.5).wait(2)
    r = run("twofinger", s)
    ok &= check("two-finger hold exits", r,
                ("stops via the failsafe", stop_reason(r) == "two-finger hold"))

    # 5. a panel that never reports lifts still works (pause ends the gesture)
    s = exit_taps(Scenario(lifts=False).wait(1)).wait(2)
    r = run("nolifts", s)
    ok &= check("no finger-lift events: tap and Exit still work", r,
                ("stops via exit button", stop_reason(r) == "exit button"))

    # 6. the kernel omits unchanged coordinates: same-row taps and swipes still work
    s = (Scenario().wait(1)
         .swipe(1100, 500, 300, 500)       # next -> 1
         .swipe(1100, 500, 300, 500)       # same start row and column again -> 2
         .tap(300, 500)                    # tap where the last swipe ended: opens bar
         .tap(nx, ny)                      # -> 3
         .tap(nx, ny)                      # identical spot, no coordinates sent -> 4
         .wait(2))
    r = run("samecoords", s)
    ok &= check("taps and swipes that repeat a coordinate", r,
                ("fifth work saved", "pos=5\n" in r["state"]),
                ("bar opened", "bar shown" in r["log"]))

    # 7. sleep: idle -> sleeps until the next change; the clock wakes it for the change
    sleep_conf = "INTERVAL=3600\nROT=0\nSLEEP=1\nAWAKE=30\n"
    s = Scenario().wait(1).tap(700, 400).wait(40)
    r = run("sleep", s, config=sleep_conf)
    log = r["log"]
    ok &= check("idle: closes the bar, sleeps, wakes for the next artwork", r,
                ("bar was shown", "bar shown" in log),
                ("slept until the change", "sleeping for up to 35" in log),
                ("advanced after waking", "showing 2/5" in log),
                ("slept again after the change", log.count("awake after") >= 2),
                ("no errors", "ERROR" not in log))

    # 8. power button opens the bar; again closes it and sleeps right away
    s = Scenario().wait(1).power().wait(2).power().wait(5)
    r = run("power", s, config=sleep_conf)
    log = r["log"]
    i_bar, i_sleep = log.find("bar shown"), log.find("sleeping for up to")
    ok &= check("power button: open bar, then close and sleep", r,
                ("bar opened by the button", i_bar >= 0),
                ("slept within seconds of the second press", 0 <= i_bar < i_sleep),
                ("no errors", "ERROR" not in log))

    # 9. frontlight: off before sleeping, stays off through automatic changes,
    #    back on with the power button, off again when it sleeps
    s = Scenario().wait(40).power().wait(2).power().wait(6)
    r = run("light", s, config=sleep_conf)
    events = [l.split("frontlight ", 1)[1].split(" ")[0] for l in r["log"].splitlines()
              if " frontlight o" in l]
    ok &= check("frontlight only on when someone interacts", r,
                ("off, on (button), off (sleep)", events[:3] == ["off", "on", "off"]),
                ("back to the user's level when on", "frontlight on (800)" in r["log"]),
                ("ends off while asleep", r["light"] == "0"),
                ("stays off across the automatic change",
                 r["log"].find("showing 2/5") < r["log"].find("frontlight on")
                 or "showing 2/5" not in r["log"]))

    # 10. images unreadable (USB drive mode): keeps running, keeps the picture
    s = Scenario().wait(1).swipe(1100, 500, 300, 500).tap(700, 400).wait(70)
    r = run("usb", s, images=False)
    ok &= check("images away (USB): no crash, no change, bar still works", r,
                ("ran to the end", stop_reason(r) == "input stream ended"),
                ("logged the missing file", "keeping the current picture" in r["log"]),
                ("bar shown", "bar shown" in r["log"]),
                ("no errors", "ERROR" not in r["log"]))

    # 10b. collections: open from the bar, untick one, Listo -> only the other plays
    cx, cy = bar_button("settings")
    left, right, done = SETTINGS["coll1"], SETTINGS["coll2"], SETTINGS["done"]
    s = (Scenario().wait(1).tap(700, 400).tap(cx, cy).tap(*left).tap(*done)
         .swipe(1100, 500, 300, 500).swipe(1100, 500, 300, 500).wait(1))
    r = run("colls", s, content={"barroco": 3, "romanticismo": 2})
    shown = [l.split("(")[-1].rstrip(")") for l in r["log"].splitlines() if "showing" in l]
    ok &= check("collections: untick Barroco, only Romanticismo plays", r,
                ("screen shown", "settings shown" in r["log"]),
                ("saved in config", "OFF=barroco" in r["config"]),
                ("only romanticismo after Listo", shown[-3:] == ["romanticismo"] * 3),
                ("bar names the collection", "Barroco · 1/5" in r["fbink"]),
                ("no errors", "ERROR" not in r["log"]))

    # 10c. the last ticked collection cannot be unticked
    s = Scenario().wait(1).tap(700, 400).tap(cx, cy).tap(*left).tap(*right).tap(*done).wait(1)
    r = run("lastone", s, content={"barroco": 3, "romanticismo": 2})
    ok &= check("the last ticked collection stays on", r,
                ("refused", "the last one stays on" in r["log"]),
                ("romanticismo still on", "OFF=barroco\n" in r["config"]))

    # 10d. shuffle: a full cycle shows every work once, then a new order
    s = Scenario().wait(1)
    for _ in range(11):
        s.swipe(1100, 500, 300, 500)
    r = run("shuffle", s.wait(1), content={"barroco": 4, "romanticismo": 2}, shuffle=True)
    shown = [l.split(": ", 1)[1].split(" - ")[0] for l in r["log"].splitlines() if "showing" in l]
    ok &= check("shuffle: every work once per cycle", r,
                ("first cycle has all 6", len(set(shown[:6])) == 6),
                ("second cycle has all 6", len(set(shown[6:12])) == 6))

    # 11. SLEEP=0 never sleeps
    r = run("nosleep", Scenario().wait(1).tap(700, 400).wait(80))
    ok &= check("SLEEP=0 stays awake", r, ("never slept", "sleeping" not in r["log"]))

    # 12. battery: badge at 15% or less, charge screen at 5% or less, nothing when charging
    s = Scenario().wait(2)
    r = run("battlow", s, env={"ART_BATTERY": "14"})
    ok &= check("low battery: badge over the painting", r,
                ("badge drawn", "Batería baja · 14%" in r["fbink"]),
                ("painting shown", "file=" in r["fbink"]))
    r = run("battempty", s, env={"ART_BATTERY": "4"})
    ok &= check("nearly empty battery: charge screen instead of a painting", r,
                ("charge screen", "Por favor, carga el Kindle" in r["fbink"]),
                ("no painting", "file=" not in r["fbink"]))
    r = run("battcharging", s, env={"ART_BATTERY": "4", "ART_CHARGING": "1"})
    ok &= check("charging: no badge, no charge screen", r,
                ("no warning", "Batería baja" not in r["fbink"] and "carga el Kindle" not in r["fbink"]))

    # 13. the bar shows long titles whole, in a smaller size
    long = "El ojo, como un globo extraño, se dirige hacia el infinito"
    r = run("longtitle", Scenario().wait(1).tap(700, 400).wait(1), title=long)
    ok &= check("long title: whole, smaller font", r,
                ("whole title", f" {long}\n" in r["fbink"]),
                ("smaller than 46px", "px=46" not in r["fbink"].split(long)[0].splitlines()[-1]))

    # 14. saving the config keeps lines that belong to other programs
    s = Scenario().wait(1).tap(700, 400).tap(sx, sy).tap(*SETTINGS["1h"]).tap(*SETTINGS["done"]).wait(1)
    r = run("otherkeys", s, config="INTERVAL=60\nROT=0\nSLEEP=0\nREPO=someone/their-gallery\n")
    ok &= check("config: other programs' lines survive a save", r,
                ("interval saved", "INTERVAL=60\n" not in r["config"]),
                ("REPO kept", "REPO=someone/their-gallery" in r["config"]))

    # 15. the exit asks first: No goes back to Ajustes, and the gallery keeps running
    s = (Scenario().wait(1).tap(700, 400).tap(sx, sy).tap(*SETTINGS["exit"])
         .tap(*SETTINGS["stay"]).tap(*SETTINGS["done"]).wait(2))
    r = run("exitno", s)
    ok &= check("exit: No keeps the gallery running", r,
                ("asked", "exit confirmation shown" in r["log"]),
                ("cancelled", "exit cancelled" in r["log"]),
                ("still running", stop_reason(r) == "input stream ended"),
                ("Ajustes shown again", r["log"].count("settings shown") == 2))

    # 16. Ajustes and the confirmation close by themselves after a minute
    s = Scenario().wait(1).tap(700, 400).tap(sx, sy).tap(*SETTINGS["exit"]).wait(65)
    r = run("exittimeout", s)
    ok &= check("exit confirmation times out back to the painting", r,
                ("still running", stop_reason(r) == "input stream ended"),
                ("painting again", r["log"].rfind("showing") > r["log"].find("exit confirmation shown")))

    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
