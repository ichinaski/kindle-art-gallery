#!/bin/sh
# Name: 3. Autostart on/off
# Author: art
# Switch starting the gallery at boot on or off (the file art/no-autostart).
F=/mnt/us/art/no-autostart
FBINK=/mnt/us/libkh/bin/fbink
if [ -f "$F" ]; then
  rm -f "$F"
  $FBINK -q -m -y -5 "Arranque automatico: ACTIVADO"
else
  : >"$F"
  $FBINK -q -m -y -5 "Arranque automatico: DESACTIVADO"
fi
