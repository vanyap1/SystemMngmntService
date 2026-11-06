#!/bin/sh
# Install the GPIO power button service and restart the OLED service.
# Usage: sudo sh /home/vanya/power-button/install.sh
set -e
[ "$(id -u)" = 0 ] || { echo "run with sudo"; exit 1; }
cd "$(dirname "$0")"

install -m 0755 power-button.py      /usr/local/sbin/power-button
install -m 0644 power-button.service /etc/systemd/system/power-button.service
[ -f /etc/default/power-button ] || install -m 0644 power-button.default /etc/default/power-button

systemctl daemon-reload
systemctl enable --now power-button.service
systemctl restart oled.service          # picks up the new shutdown screen

systemctl --no-pager --lines=5 status power-button.service
