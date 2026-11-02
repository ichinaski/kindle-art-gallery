#!/bin/sh
# Start the art gallery (idempotent). Copies the program to RAM and runs it from
# there, so a USB connection to a computer (which takes /mnt/us away) cannot pull
# the scripts from under it. Images, config and state stay in /mnt/us/art.
DIR=/mnt/us/art
RUN=/tmp/art-run
PIDFILE=/tmp/art-gallery.pid   # tmpfs: cannot outlive a restart

pid=$(cat "$PIDFILE" 2>/dev/null)
if [ -n "$pid" ] && tr '\0' ' ' <"/proc/$pid/cmdline" 2>/dev/null | grep -q "art-run/gallery.sh"; then
  echo "art gallery already running (pid $pid)"
  exit 0
fi

rm -rf "$RUN"
mkdir -p "$RUN/bin" "$RUN/fonts" || exit 1
cp "$DIR/artd.lua" "$DIR/gallery.sh" "$DIR/ui.sh" "$RUN/" &&
  cp "$DIR/bin/evtap" "$RUN/bin/" &&
  cp "$DIR/fonts/"*.ttf "$RUN/fonts/" || { echo "cannot copy the program to $RUN"; exit 1; }
cp "$DIR/widths.lua" "$RUN/" 2>/dev/null # text measuring; without it, a rough estimate
chmod +x "$RUN/bin/evtap"

setsid sh "$RUN/gallery.sh" >/dev/null 2>&1 </dev/null &
echo $! >"$PIDFILE"
echo "art gallery started (pid $!)"
