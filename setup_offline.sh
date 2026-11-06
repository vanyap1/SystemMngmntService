#!/bin/bash
# Kept for old instructions: the installer is install.sh (menu, online/offline, offline bundles, service).
exec "$(dirname "${BASH_SOURCE[0]}")/install.sh" offline "$@"
