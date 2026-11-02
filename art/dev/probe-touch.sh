#!/bin/sh
# Probe 1: with the Kindle UI paused (X still running), can we grab and read the
# touchscreen, and does it report finger lifts? Writes probe-touch.txt.
# Takes about 25 seconds, then the Kindle UI comes back.
DIR=/mnt/us/art
if [ "$1" != "--run" ]; then
  setsid sh "$0" --run >/dev/null 2>&1 </dev/null &
  echo "touch probe running, results in $DIR/probe-touch.txt"
  exit 0
fi

. "$DIR/ui.sh"
OUT=$DIR/probe-touch.txt
sleep 2
# dead-man's switch: resume the UI even if something below hangs
( sleep 60; . "$DIR/ui.sh"; ui_resume ) >/dev/null 2>&1 &
DEADMAN=$!
ui_pause
trap 'ui_resume; kill $DEADMAN 2>/dev/null' EXIT
{
  echo "== $(date)"
  echo "x: $(initctl status x 2>&1 | head -1)"
  echo "framework: $(initctl status framework 2>&1 | head -1)"
  echo "cvm: $(grep State /proc/"$(pidof cvm | cut -d' ' -f1)"/status 2>/dev/null)"
  echo
  echo "== 10 s: TAP a few times, SWIPE once, HOLD one finger still for 3 s"
  $FBINK -q -c -m -M "Prueba tactil (10 s): toca, desliza, y deja un dedo quieto 3 s"
  "$DIR/bin/evtap" -p 10 -g /dev/input/event2
  echo "evtap exit $?"
  echo
  echo "== 8 s: hold TWO fingers on the screen for 3 s"
  $FBINK -q -c -m -M "Ahora: pon DOS dedos y mantenlos 3 s"
  "$DIR/bin/evtap" -p 8 -g /dev/input/event2
  echo "evtap exit $?"
} >"$OUT" 2>&1
$FBINK -q -c -m -M "Listo, volviendo al Kindle"
sleep 1
ui_resume >>"$OUT" 2>&1
kill "$DEADMAN" 2>/dev/null
trap - EXIT
