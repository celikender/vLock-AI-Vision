#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"
sudo apt-get update
sudo apt-get install -y ffmpeg v4l-utils python3
root=$(pwd)
user=$(id -un)
sudo usermod -aG video "$user"
sudo tee /etc/systemd/system/vlock-playground-camera.service >/dev/null <<EOF
[Unit]
Description=vLock playground USB camera
After=network.target
[Service]
User=$user
SupplementaryGroups=video
ExecStart=/usr/bin/python3 "$root/server.py"
Restart=always
RestartSec=3
NoNewPrivileges=true
[Install]
WantedBy=multi-user.target
EOF
sudo systemctl daemon-reload
sudo systemctl enable --now vlock-playground-camera
hostname -I
echo 'Open http://<Pi-IP>:8080 from your PC on the same network.'
