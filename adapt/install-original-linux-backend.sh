#!/bin/sh
set -eu

BIN="${1:-./lalune-original-linux-arm64}"
if [ ! -x "$BIN" ] && [ -x /tmp/lalune-original-linux-arm64 ]; then BIN=/tmp/lalune-original-linux-arm64; fi
if [ ! -x "$BIN" ] && [ -x /tmp/lalune-backend-linux-arm64 ]; then BIN=/tmp/lalune-backend-linux-arm64; fi
BUNDLE_DIR="${2:-$(CDPATH= cd -- "$(dirname -- "$BIN")" && pwd -P)}"
INSTALL=/usr/local/bin/lalune-backend
DEPLOY_MANAGER=/usr/local/bin/deploy-manager
DEPLOY_LIB=/usr/local/lib/lalune
ASSET_DIR=$DEPLOY_LIB/server-assets
DEPLOY_MARKER=$DEPLOY_LIB/.managed-by-lalune-deploy
SERVICE=/etc/systemd/system/lalune-backend.service

[ -x "$BIN" ] || { echo "LaLune backend binary not found: $BIN" >&2; exit 1; }
[ -x "$BUNDLE_DIR/deploy-manager" ] || { echo "DeployManager binary missing beside the backend bundle: $BUNDLE_DIR/deploy-manager" >&2; exit 1; }
for asset in install-csqtt-lalune.sh uninstall-csqtt-lalune.sh csqtt-lalune-linux-arm64 csqtt-lalune-linux-amd64; do
    [ -s "$BUNDLE_DIR/server-assets/$asset" ] || { echo "Required deployment asset missing: $BUNDLE_DIR/server-assets/$asset" >&2; exit 1; }
done

[ ! -L "$DEPLOY_LIB" ] || { echo "Refusing symlinked deployment library: $DEPLOY_LIB" >&2; exit 1; }
[ ! -L "$ASSET_DIR" ] || { echo "Refusing symlinked deployment assets: $ASSET_DIR" >&2; exit 1; }
[ ! -L "$DEPLOY_MANAGER" ] || { echo "Refusing symlinked DeployManager: $DEPLOY_MANAGER" >&2; exit 1; }
[ ! -L "$DEPLOY_MARKER" ] || { echo "Refusing symlinked ownership marker: $DEPLOY_MARKER" >&2; exit 1; }
if [ -e "$DEPLOY_MARKER" ] && [ "$(cat "$DEPLOY_MARKER")" != "LALUNE-DEPLOY-BUNDLE-V1" ]; then
    echo "Deployment ownership marker mismatch; refusing to overwrite deployment assets." >&2
    exit 1
fi
if [ -e "$DEPLOY_MANAGER" ] && [ ! -f "$DEPLOY_MARKER" ]; then
    echo "DeployManager exists without the LaLune ownership marker; refusing to overwrite it." >&2
    exit 1
fi
if [ -e "$ASSET_DIR" ] && [ ! -f "$DEPLOY_MARKER" ]; then
    echo "Deployment assets exist without the LaLune ownership marker; refusing to adopt them." >&2
    exit 1
fi

install -m 0755 "$BIN" "$INSTALL"
install -m 0755 "$BUNDLE_DIR/deploy-manager" "$DEPLOY_MANAGER"
install -d -m 0755 "$ASSET_DIR"
for asset in install-csqtt-lalune.sh uninstall-csqtt-lalune.sh csqtt-lalune-linux-arm64 csqtt-lalune-linux-amd64; do
    install -m 0755 "$BUNDLE_DIR/server-assets/$asset" "$ASSET_DIR/$asset"
done
printf '%s\n' 'LALUNE-DEPLOY-BUNDLE-V1' > "$DEPLOY_MARKER"
chmod 0644 "$DEPLOY_MARKER"

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
