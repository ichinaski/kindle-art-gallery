#!/bin/sh
# Build evtap as a static ARM binary for the Kindle (needs uv; zig comes from PyPI).
# Soft-float EABI: a fully static binary runs on both soft- and hard-float firmware.
set -e
cd "$(dirname "$0")"
mkdir -p ../bin
uv run -q --with ziglang python -m ziglang cc -target arm-linux-musleabi -static -Os -s \
  -Wall -Wextra -o ../bin/evtap evtap.c
file ../bin/evtap
