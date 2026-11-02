#!/bin/sh
# Stop the gallery (e.g. over SSH). Killing artd.lua is enough: gallery.sh notices
# and resumes the Kindle UI.
for proc in /proc/[0-9]*; do
  pid=${proc#/proc/}
  [ "$pid" = "$$" ] && continue
  cmd=$(tr "\0" " " <"$proc/cmdline" 2>/dev/null)
  case "$cmd" in *"art-run/artd.lua"*|*"/mnt/us/art/artd.lua"*) kill "$pid" 2>/dev/null ;; esac
done
echo "art gallery stopping"
