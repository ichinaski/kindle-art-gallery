#!/bin/sh
# Probe 2: with the Kindle UI paused and preventScreenSaver=1, what does a short
# press of the power button do? Phase 1 only listens; phase 2 grabs the power keys
# to see whether that hides the press from powerd. Writes probe-power.txt. If the screen goes to sleep, press the button again to wake it.
DIR=/mnt/us/art
if [ "$1" != "--run" ]; then
  setsid sh "$0" --run >/dev/null 2>&1 </dev/null &
  echo "power probe running, results in $DIR/probe-power.txt"
  exit 0
fi

. "$DIR/ui.sh"
OUT=$DIR/probe-power.txt
POWER="/dev/input/event0 /dev/input/event1"
sleep 2
# dead-man's switch: resume the UI even if something below hangs
( sleep 90; . "$DIR/ui.sh"; ui_resume ) >/dev/null 2>&1 &
DEADMAN=$!
ui_pause
trap 'ui_resume; kill $DEADMAN 2>/dev/null' EXIT

# log powerd events (goingToScreenSaver, suspending, ...) in the background
lipc-wait-event -m com.lab126.powerd '*' 2>&1 | while read -r line; do
  echo "$(cut -d' ' -f1 /proc/uptime) powerd: $line"
done >>"$OUT.events" &
WATCH=$!

phase() { # $1 = label, $2 = evtap device args
  echo "== $1"
  echo "date $(date +%s) uptime $(cut -d' ' -f1 /proc/uptime) powerd $(lipc-get-prop com.lab126.powerd status 2>/dev/null | head -3 | tr '\n' ' ')"
  # shellcheck disable=SC2086
  "$DIR/bin/evtap" -p 15 $2
  echo "date $(date +%s) uptime $(cut -d' ' -f1 /proc/uptime) (a big gap between the two clocks means it suspended)"
  echo
}

rm -f "$OUT.events"
{
  echo "== $(date)"
  $FBINK -q -c -m -M "Fase 1 (15 s): pulsa el boton de encendido UNA vez, corto"
  phase "phase 1: listen only" "$POWER"
  $FBINK -q -c -m -M "Fase 2 (15 s): pulsalo otra vez, corto"
  phase "phase 2: power keys grabbed" "-g /dev/input/event0 -g /dev/input/event1"
} >"$OUT" 2>&1
kill "$WATCH" 2>/dev/null
killall lipc-wait-event 2>/dev/null
{ echo "== powerd events"; cat "$OUT.events" 2>/dev/null; } >>"$OUT"
rm -f "$OUT.events"
$FBINK -q -c -m -M "Listo, volviendo al Kindle"
sleep 1
ui_resume >>"$OUT" 2>&1
kill "$DEADMAN" 2>/dev/null
trap - EXIT
