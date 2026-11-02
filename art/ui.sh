#!/bin/sh
# Pause and resume the Kindle UI. Sourced by gallery.sh and the probe scripts.
#
# The UI is frozen (SIGSTOP), not stopped: X keeps running, and resuming is
# instant, with no restart of upstart jobs and no reboot. This is what KOReader
# does when it runs alongside the framework.
FBINK=${FBINK:-/mnt/us/libkh/bin/fbink}
FB_ROTATE=/sys/class/graphics/fb0/rotate
ROT_SAVE=/tmp/art-rotate.orig
WIFI_SAVE=/tmp/art-wifi.orig
LIGHT_SAVE=/tmp/art-light.orig
LIGHT=$(ls -d /sys/class/backlight/* 2>/dev/null | head -1)

ui_pause() {
  cat "$FB_ROTATE" >"$ROT_SAVE" 2>/dev/null
  lipc-get-prop com.lab126.cmd wirelessEnable >"$WIFI_SAVE" 2>/dev/null
  [ -n "$LIGHT" ] && cat "$LIGHT/brightness" >"$LIGHT_SAVE" 2>/dev/null
  lipc-set-prop com.lab126.powerd preventScreenSaver 1 >/dev/null 2>&1
  lipc-set-prop com.lab126.pillow disableEnablePillow disable >/dev/null 2>&1
  killall -STOP cvm awesome 2>/dev/null
  echo "ui paused (rotation was $(cat "$ROT_SAVE" 2>/dev/null))"
}

ui_resume() {
  # rotation first: the UI expects the framebuffer the way it left it
  [ -s "$ROT_SAVE" ] && cat "$ROT_SAVE" >"$FB_ROTATE" 2>/dev/null
  killall -CONT awesome cvm 2>/dev/null
  lipc-set-prop com.lab126.pillow disableEnablePillow enable >/dev/null 2>&1
  lipc-set-prop com.lab126.powerd preventScreenSaver 0 >/dev/null 2>&1
  # the gallery turns the frontlight off to sleep; give back the user's level
  [ -n "$LIGHT" ] && [ -s "$LIGHT_SAVE" ] && cat "$LIGHT_SAVE" >"$LIGHT/brightness" 2>/dev/null
  # the gallery may have turned Wi-Fi off (WIFI=0)
  [ "$(cat "$WIFI_SAVE" 2>/dev/null)" = "1" ] && lipc-set-prop com.lab126.cmd wirelessEnable 1 >/dev/null 2>&1
  # repaint: our image is still in the framebuffer until the UI draws again.
  # Open the Library (the library items live there), or Home if that fails.
  lipc-set-prop com.lab126.appmgrd start "app://com.lab126.KPPMainApp?view=KPP_LIBRARY" >/dev/null 2>&1 ||
    lipc-set-prop com.lab126.appmgrd start app://com.lab126.booklet.home >/dev/null 2>&1
  echo "ui resumed"
}
