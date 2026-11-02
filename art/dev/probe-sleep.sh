#!/bin/sh
# Probe 3: can the gallery own the power button and sleep between interactions?
#   A. power keys grabbed, UI paused: does powerd still react to a short press?
#   B. suspend (rtcwake, 40 s): does a press wake it early, and do we get the key?
#   C. suspend (20 s), no press: does the clock alarm wake it on time?
# Waits for a tap before starting. Writes probe-sleep.txt. A dead-man's switch
# resumes the UI after 5 minutes whatever happens.
DIR=/mnt/us/art
if [ "$1" != "--run" ]; then
  setsid sh "$0" --run >/dev/null 2>&1 </dev/null &
  echo "sleep probe running, results in $DIR/probe-sleep.txt"
  exit 0
fi

. "$DIR/ui.sh"
OUT=$DIR/probe-sleep.txt
EVTAP=$DIR/bin/evtap
KEYS="-g /dev/input/event0 -g /dev/input/event1"
up() { cut -d' ' -f1 /proc/uptime; }
say() { $FBINK -q -c -m -M "$1"; echo "$(up) screen: $1"; }

sleep 2
( sleep 300; . "$DIR/ui.sh"; ui_resume ) >/dev/null 2>&1 &
DEADMAN=$!
ui_pause >/dev/null 2>&1
trap 'ui_resume >/dev/null 2>&1; kill $DEADMAN 2>/dev/null' EXIT

lipc-wait-event -m com.lab126.powerd '*' 2>&1 | while read -r line; do
  echo "$(up) powerd event: $line"
done >/tmp/probe-sleep.events &

suspend_for() { # seconds
  echo enabled >/sys/class/rtc/rtc0/device/power/wakeup 2>/dev/null
  sync
  t0=$(date +%s)
  rtcwake -d /dev/rtc0 -m mem -s "$1" 2>&1 | sed 's/^/  rtcwake: /'
  echo "  asked $1 s, woke after $(( $(date +%s) - t0 )) s"
}

{
  echo "== $(date)"
  say "Prueba de reposo: toca la pantalla para empezar"
  timeout 600 "$EVTAP" -p 600 -g /dev/input/event2 | grep -m1 TRACKING_ID >/dev/null
  echo "$(up) started"

  echo; echo "== A: power keys grabbed, press once"
  say "A (15 s): pulsa el boton de encendido UNA vez, corto"
  "$EVTAP" -p 15 $KEYS | grep -e KEY -e grab
  echo "powerd: $(lipc-get-prop com.lab126.powerd state 2>&1)"

  echo; echo "== B: suspend 40 s, press to wake after ~5 s"
  say "B: se dormira. Espera 5 s y pulsa el boton para despertarlo"
  sleep 3
  "$EVTAP" -p 70 $KEYS >/tmp/probe-sleep.keys 2>&1 &
  K=$!
  sleep 1
  suspend_for 40
  say "B: despierto"
  sleep 4
  kill $K 2>/dev/null
  echo "  keys seen:"; grep -e KEY -e grab /tmp/probe-sleep.keys | sed 's/^/    /'
  echo "powerd: $(lipc-get-prop com.lab126.powerd state 2>&1)"

  echo; echo "== C: suspend 20 s, do not press"
  say "C: se dormira 20 s. NO toques nada"
  sleep 3
  suspend_for 20
  say "C: despierto. Fin de la prueba"
  sleep 3
  echo "powerd: $(lipc-get-prop com.lab126.powerd state 2>&1)"
  echo "wifi: $(lipc-get-prop com.lab126.wifid cmState 2>&1)"
} >"$OUT" 2>&1

killall lipc-wait-event 2>/dev/null
{ echo; echo "== powerd events"; cat /tmp/probe-sleep.events; } >>"$OUT"
ui_resume >>"$OUT" 2>&1
kill "$DEADMAN" 2>/dev/null
trap - EXIT
echo "== done" >>"$OUT"
