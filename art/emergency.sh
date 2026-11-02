#!/bin/sh
# Boot hook: the jailbreak's /etc/upstart/kmc.conf runs /mnt/us/emergency.sh on
# every boot, once the Kindle UI is ready (framework_ready). We use it to start the
# art gallery. To boot to the normal Kindle UI instead, create the file
# /mnt/us/art/no-autostart (library item "Autostart on/off", or over USB).
# Delete this file to remove the hook entirely.
[ -f /mnt/us/art/no-autostart ] && exit 0
[ -f /mnt/us/art/start-art.sh ] || exit 0
# give the home screen time to settle, then start, fully detached from upstart
setsid sh -c 'sleep 45; sh /mnt/us/art/start-art.sh' >/dev/null 2>&1 </dev/null &
exit 0
