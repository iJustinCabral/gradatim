#!/usr/bin/env bash
# =============================================================================
# Gradatim — One-command server setup script
#
# Tested on Ubuntu 22.04+ / Debian 12+ / Amazon Linux 2023
#
# Usage:
#   curl -sSL <your-host>/deploy/setup.sh | bash
#   # or
#   chmod +x deploy/setup.sh && ./deploy/setup.sh
# =============================================================================
set -euo pipefail

APP_DIR="${GRADATIM_DIR:-/opt/gradatim}"
PORT="${GRADATIM_PORT:-8080}"
USER="gradatim"

echo "======================================"
echo "  Gradatim — Server Setup"
echo "======================================"
echo ""

# --- Detect package manager ---
if command -v apt-get &>/dev/null; then
    PM="apt"
elif command -v yum &>/dev/null; then
    PM="yum"
elif command -v dnf &>/dev/null; then
    PM="dnf"
else
    echo "ERROR: No supported package manager found (apt/yum/dnf)."
    exit 1
fi

# --- Install Python 3.11+ if needed ---
if ! command -v python3 &>/dev/null; then
    echo "Installing Python 3..."
    if [ "$PM" = "apt" ]; then
        sudo apt-get update -qq
        sudo apt-get install -y -qq python3
    else
        sudo $PM install -y python3
    fi
fi

PYVER=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
echo "Python version: $PYVER"

# --- Create system user ---
if ! id "$USER" &>/dev/null; then
    echo "Creating system user: $USER"
    sudo useradd -r -m -s /bin/false "$USER" || true
fi

# --- Deploy application ---
echo "Deploying to $APP_DIR..."
sudo mkdir -p "$APP_DIR"
sudo cp -r gradatim/ "$APP_DIR/"
sudo cp -r tests/ "$APP_DIR/" 2>/dev/null || true
sudo chown -R "$USER:$USER" "$APP_DIR"

# --- Create systemd service ---
echo "Installing systemd service..."
sudo tee /etc/systemd/system/gradatim.service > /dev/null <<UNIT
[Unit]
Description=Gradatim — Collaborative Compute Network
After=network.target

[Service]
Type=simple
User=$USER
Group=$USER
WorkingDirectory=$APP_DIR
ExecStart=/usr/bin/python3 -m gradatim web --host 0.0.0.0 --port $PORT
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal

# Security hardening
NoNewPrivileges=yes
ProtectSystem=strict
ProtectHome=yes
ReadWritePaths=$APP_DIR
PrivateTmp=yes

[Install]
WantedBy=multi-user.target
UNIT

sudo systemctl daemon-reload
sudo systemctl enable gradatim
sudo systemctl start gradatim

echo ""
echo "======================================"
echo "  Gradatim is running!"
echo "  http://$(hostname -I | awk '{print $1}'):$PORT"
echo ""
echo "  Commands:"
echo "    sudo systemctl status gradatim"
echo "    sudo journalctl -u gradatim -f"
echo "    sudo systemctl restart gradatim"
echo "======================================"
