#!/usr/bin/env bash
set -e

echo "=== Instalacja zależności systemowych ==="
sudo apt update
# Instalujemy v4l-utils (dla v4l2-ctl) oraz biblioteki Pythona
sudo apt install -y v4l-utils python3-flask python3-numpy python3-opencv libgl1 libglib2.0-0

echo "=== Konfiguracja usługi systemd ==="
CURRENT_DIR=$(pwd)
CURRENT_USER=$USER

sudo tee /etc/systemd/system/purethermal-server.service > /dev/null << EOF
[Unit]
Description=PureThermal Y16 Flask Server
After=network.target

[Service]
User=$CURRENT_USER
WorkingDirectory=$CURRENT_DIR
ExecStart=/usr/bin/python3 $CURRENT_DIR/thermal_server.py
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

echo "=== Uruchamianie usługi ==="
sudo systemctl daemon-reload
sudo systemctl enable purethermal-server
sudo systemctl restart purethermal-server

echo "=========================================="
echo "Gotowe! Serwer wystartował w tle."
echo "Zarządzaj usługą: sudo systemctl status purethermal-server"
echo "=========================================="

