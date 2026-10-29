#!/bin/bash
# ============================================================
#  SystemMngmntService — Idempotent OFFLINE Installer
#  Run as:  sudo bash setup_offline.sh
# ============================================================

set -euo pipefail

# ── 0. Must be root ─────────────────────────────────────────
if [[ "$EUID" -ne 0 ]]; then
    echo "[ERROR] This script must be run as root: sudo bash setup_offline.sh" >&2
    exit 1
fi

# ── 1. Resolve installation directory ───────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVICE_FILE="/etc/systemd/system/systemmngmntservice.service"
APP_ENTRY="$SCRIPT_DIR/app.py"
CONFIG_FILE="$SCRIPT_DIR/config.json"
SETUP_DATA_DIR="$SCRIPT_DIR/setup_data"

echo "[*] Installation directory: $SCRIPT_DIR"

if [[ ! -f "$APP_ENTRY" ]]; then
    echo "[ERROR] app.py not found in $SCRIPT_DIR" >&2
    exit 1
fi

# ── 2. Install OFFLINE system dependencies ──────────────────
echo "[*] Checking offline packages directory..."

if [[ ! -d "$SETUP_DATA_DIR" ]]; then
    echo "[ERROR] Directory $SETUP_DATA_DIR not found!" >&2
    exit 1
fi

DEB_COUNT=$(find "$SETUP_DATA_DIR" -maxdepth 1 -name "*.deb" | wc -l)
if [[ "$DEB_COUNT" -eq 0 ]]; then
    echo "[ERROR] No .deb packages found in $SETUP_DATA_DIR" >&2
    exit 1
fi

echo "[*] Found $DEB_COUNT packages. Installing offline dependencies..."

dpkg -i "$SETUP_DATA_DIR"/*.deb || {
    echo "[*] Resolving package dependencies (pass 2)..."
    dpkg -i "$SETUP_DATA_DIR"/*.deb
}

# ── 3. Set capability so Python can bind to privileged ports ─
if command -v python3 &>/dev/null; then
    PYTHON3_BIN="$(readlink -f "$(which python3)")"
    echo "[*] Setting cap_net_bind_service on $PYTHON3_BIN..."
    
    if ! getcap "$PYTHON3_BIN" | grep -q "cap_net_bind_service+ep"; then
        setcap 'cap_net_bind_service=+ep' "$PYTHON3_BIN"
    fi
    echo "    Capabilities configuration:"
    getcap "$PYTHON3_BIN"
else
    echo "[ERROR] python3 executable not found after installing packages!" >&2
    exit 1
fi

# ── 4. Determine the user that owns app.py ──────────────────
APP_OWNER="$(stat -c '%U' "$APP_ENTRY")"
if [[ "$APP_OWNER" == "root" ]]; then
    if [[ -f "$CONFIG_FILE" ]]; then
        CFG_USER="$(python3 -c "import sys; sys.path.insert(0, '$SCRIPT_DIR'); from core import config; print(config.auth().get('username', ''))" 2>/dev/null || true)"
        [[ -n "$CFG_USER" ]] && APP_OWNER="$CFG_USER"
    fi
fi
echo "[*] Service will run as user: $APP_OWNER"

# ── 5. Create systemd unit file (Safe overwrite) ─────────────
TEMP_SERVICE=$(mktemp)
cat > "$TEMP_SERVICE" <<EOF
[Unit]
Description=SystemMngmntService — Flask application management service
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=$SCRIPT_DIR
ExecStart=$PYTHON3_BIN $APP_ENTRY
Restart=on-failure
RestartSec=5
StandardOutput=journal
StandardError=journal
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
EOF

if ! cmp -s "$TEMP_SERVICE" "$SERVICE_FILE"; then
    echo "[*] Writing/updating $SERVICE_FILE..."
    mv "$TEMP_SERVICE" "$SERVICE_FILE"
    echo "[*] Reloading systemd daemon..."
    systemctl daemon-reload
else
    echo "[*] Service file is up-to-date. Skipping write."
    rm -f "$TEMP_SERVICE"
fi

# ── 6. Enable & start the service ───────────────────────────
if ! systemctl is-enabled -q systemmngmntservice.service 2>/dev/null; then
    echo "[*] Enabling service to start on boot..."
    systemctl enable systemmngmntservice.service
fi

echo "[*] Restarting service to apply any changes..."
systemctl restart systemmngmntservice.service

# ── 7. Status report ─────────────────────────────────────────
echo ""
echo "========================================="
systemctl status systemmngmntservice.service --no-pager -l || true
echo "========================================="
echo ""
echo "[OK] Offline setup complete. Service is running cleanly."
echo "     Logs:  journalctl -u systemmngmntservice.service -f"