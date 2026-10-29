#!/bin/sh
# Regenerate the README screenshots in docs/img (needs chromium).
# Start two dev servers first and let the monitor collect a few minutes of history:
#   python3 tests/devserver.py --port 5099 &          # logged-in view
#   python3 tests/devserver.py --port 5098 --auth &   # anonymous view
#   python3 tests/devserver.py --port 5097 --logs testLogs &   # log viewer with real run logs
#   tests/docs_screenshots.sh
set -e
cd "$(dirname "$0")/.."
S=tests/screenshot.sh
O=docs/img
# keep both monitor samplers alive (30 s lease) while the screenshots are taken
( while :; do curl -s -o /dev/null http://127.0.0.1:5099/api/monitor; curl -s -o /dev/null http://127.0.0.1:5098/api/monitor; sleep 5; done ) &
POLLER=$!
trap 'kill $POLLER' EXIT
# a finished run for the Tests page
curl -s -o /dev/null -H 'Content-Type: application/json' -d '{"script":"demo_random_test.py","serial":"SN-0042"}' \
    http://127.0.0.1:5099/api/tests/start
sleep 12
$S /                                   $O/dashboard.png       1400x1150 9000
$S /                                   $O/dashboard-anonymous.png 1400x1120 9000 5098
$S '/tests?js=MonitorFloat.open()'     $O/monitor-window.png  1400x900  9000
$S '/tests?js=MonitorFloat.close()'    $O/tests.png           1400x900  9000
$S "/editor?js=openFile('$PWD/core/monitor.py','monitor.py',document.createElement('div'))" $O/editor.png 1400x770 9000
$S "/settings?js=Devices.open();Devices.setTab('buses');setTimeout(()=>Devices.tabs.buses.expandAll(true),2500)" $O/devices-buses.png 1400x900 9000
$S "/settings?js=Devices.open();Devices.setTab('net');setTimeout(()=>{const n=Devices.tabs.net;n.expanded.add('end0');n.toggleRoutes()},2500)" $O/devices-network.png 1400x900 9000
$S "/settings?js=Devices.open();Devices.setTab('gpio');setTimeout(()=>Devices.tabs.gpio.expandAll(true),2500)"  $O/devices-gpio.png 1400x900 9000
$S "/settings?js=Devices.open();Devices.setTab('udev');Devices.tabs.udev.setView('rules');setTimeout(()=>Devices.tabs.udev.openRule('local','99-i2c.rules'),2500)" $O/devices-udev.png 1400x900 9000
$S /logs                               $O/logs.png            1400x900  9000 5097
$S "/logs?js=setTimeout(()=>Logs.openStep('Supply 5V'),1500)" $O/logs-step.png 1400x720 9000 5097
