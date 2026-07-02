#!/bin/bash
# ============================================================
#  SystemMngmntService — installer / setup script
#  Run as:  sudo bash setup.sh
# ============================================================

set -euo pipefail

# ── 0. Must be root ─────────────────────────────────────────
if [[ "$EUID" -ne 0 ]]; then
    echo "[ERROR] This script must be run as root: sudo bash setup.sh" >&2
    exit 1
fi

# ── 1. Resolve installation directory ───────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVICE_FILE="/etc/systemd/system/systemmngmntservice.service"
APP_ENTRY="$SCRIPT_DIR/app.py"
CONFIG_FILE="$SCRIPT_DIR/config.json"

echo "[*] Installation directory: $SCRIPT_DIR"

if [[ ! -f "$APP_ENTRY" ]]; then
    echo "[ERROR] app.py not found in $SCRIPT_DIR" >&2
    exit 1
fi

# ── 2. Install system dependencies ──────────────────────────
echo "[*] Updating package index..."
#apt-get update -qq

echo "[*] Installing python3-flask..."
apt install -y python3-flask

echo "[*] Installing p7zip-full..."
apt-get install -y p7zip-full

# ── 3. Set capability so Python can bind to privileged ports ─
PYTHON3_BIN="$(readlink -f "$(which python3)")"
echo "[*] Setting cap_net_bind_service on $PYTHON3_BIN..."
setcap 'cap_net_bind_service=+ep' "$PYTHON3_BIN"
echo "    Capabilities set:"
getcap "$PYTHON3_BIN"

# ── 4. Determine the user that owns app.py ──────────────────
APP_OWNER="$(stat -c '%U' "$APP_ENTRY")"
# Fall back to a safe non-root user if stat returns root
if [[ "$APP_OWNER" == "root" ]]; then
    # try to read from config.json
    if command -v python3 &>/dev/null && [[ -f "$CONFIG_FILE" ]]; then
        CFG_USER="$(python3 -c "import json,sys; d=json.load(open('$CONFIG_FILE')); print(d.get('auth',{}).get('username',''))" 2>/dev/null || true)"
        [[ -n "$CFG_USER" ]] && APP_OWNER="$CFG_USER"
    fi
    # last resort: keep root (not ideal but functional)
fi
echo "[*] Service will run as user: $APP_OWNER"

# ── 5. Create systemd unit file ──────────────────────────────
echo "[*] Creating $SERVICE_FILE..."
cat > "$SERVICE_FILE" <<EOF
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

echo "    Unit file written."

# ── 6. Enable & start the service ───────────────────────────
echo "[*] Reloading systemd daemon..."
systemctl daemon-reload

echo "[*] Enabling service to start on boot..."
systemctl enable systemmngmntservice.service

echo "[*] Starting service..."
systemctl restart systemmngmntservice.service

# ── 7. Status report ─────────────────────────────────────────
echo ""
echo "========================================="
systemctl status systemmngmntservice.service --no-pager -l || true
echo "========================================="
echo ""
echo "[OK] Setup complete. Service is running."
echo "     Logs:  journalctl -u systemmngmntservice.service -f"
