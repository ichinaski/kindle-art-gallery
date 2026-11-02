#!/bin/sh
# Run the gallery with the Kindle UI paused, and always give the UI back, whether
# artd.lua exits normally, crashes, or is killed. Started by start-art.sh from its
# RAM copy in /tmp/art-run; nothing here depends on /mnt/us staying mounted.
DIR=/mnt/us/art
RUN=/tmp/art-run
LOG=/tmp/gallery.log
. "$RUN/ui.sh"
exec >>"$LOG" 2>&1
echo "== $(date) gallery starting"
cd /tmp || exit 1

# let the library finish reacting to the tap before we freeze it
sleep 2

LUA_PID=
finish() {
  [ -n "$LUA_PID" ] && kill "$LUA_PID" 2>/dev/null
  ui_resume
  # logs live in RAM while running; keep a copy on the user partition if it is there
  if [ -d "$DIR" ]; then
    [ -f "$DIR/artd.log" ] && mv "$DIR/artd.log" "$DIR/artd.prev.log"
    cp /tmp/artd.log "$DIR/artd.log" 2>/dev/null
    cp "$LOG" "$DIR/gallery.log" 2>/dev/null
  fi
  rm -f /tmp/art-gallery.pid
  echo "== $(date) gallery stopped"
}
trap finish EXIT
trap 'exit 1' INT TERM HUP

ui_pause
# background + wait, so a signal to this shell is handled at once
ART_RUN="$RUN" "$(command -v lua || echo /usr/bin/lua)" "$RUN/artd.lua" &
LUA_PID=$!
wait "$LUA_PID"
echo "artd exited with status $?"
LUA_PID=
