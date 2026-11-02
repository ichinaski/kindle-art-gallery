#!/bin/sh
# Name: 2. Actualizar galería
# Author: art
# Download new or changed works from GitHub (art/artsync.sh). Only from the library,
# with the gallery stopped; progress and the result show at the bottom of the screen.
setsid sh /mnt/us/art/artsync.sh </dev/null >/dev/null 2>&1 &
