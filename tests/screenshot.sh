#!/bin/sh
# Headless Chromium screenshot of a dev-server page (start tests/devserver.py first).
#   tests/screenshot.sh <path> <out.png> [WIDTHxHEIGHT] [budget_ms] [port]
#   tests/screenshot.sh '/settings?js=MonitorFloat.open()' /tmp/x.png 1400x950
# JS errors on the page are printed to stderr (lines with "Uncaught").
path=$1; out=$2; size=${3:-1400x950}; budget=${4:-8000}; port=${5:-5099}
[ -n "$path" ] && [ -n "$out" ] || { sed -n '2,5p' "$0"; exit 2; }
timeout 90 chromium --headless=new --no-sandbox --hide-scrollbars --window-size="$(echo "$size" | tr x ,)" \
    --virtual-time-budget="$budget" --enable-logging=stderr --v=0 \
    --screenshot="$out" "http://127.0.0.1:$port$path" 2>&1 | grep -i "uncaught" >&2
[ -s "$out" ] && echo "$out"
