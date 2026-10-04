#!/bin/sh
set -eu

BIN="${1:-/tmp/lalune-backend-linux-arm64}"
INSTALL=/usr/local/bin/lalune-backend
SERVICE=/etc/systemd/system/lalune-backend.service

[ -x "$BIN" ] || { echo "ARM64 backend not found: $BIN" >&2; exit 1; }

install -m 0755 "$BIN" "$INSTALL"

cat > "$SERVICE" <<'UNIT'
[Unit]
Description=Original LaLune Linux backend (NanoPi ARM64)
After=network-online.target
Wants=network-online.target
Conflicts=lalune-gateway.service

[Service]
Type=simple
ExecStart=/usr/local/bin/lalune-backend
Restart=on-failure
RestartSec=3
Environment=RUST_LOG=info

[Install]
WantedBy=multi-user.target
UNIT

systemctl daemon-reload
systemctl enable lalune-backend
echo "Installed. Existing lalune-gateway is not modified."
