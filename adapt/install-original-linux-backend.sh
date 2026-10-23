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
SERVICE_TMP=$SERVICE.lalune-tmp
MARKER_VALUE=LALUNE-DEPLOY-BUNDLE-V1

fail() {
    echo "ERROR: $*" >&2
    exit 1
}

[ -x "$BIN" ] || fail "LaLune backend binary not found: $BIN"
[ -x "$BUNDLE_DIR/deploy-manager" ] || fail "DeployManager binary missing beside the backend bundle: $BUNDLE_DIR/deploy-manager"
for asset in deploy-csqtt-lalune.sh csqtt-lalune-linux-arm64 csqtt-lalune-linux-amd64; do
    [ -s "$BUNDLE_DIR/server-assets/$asset" ] || fail "Required deployment asset missing: $BUNDLE_DIR/server-assets/$asset"
done

# Refuse symlinks and unowned pre-existing targets before changing anything.
for path in "$INSTALL" "$DEPLOY_MANAGER" "$DEPLOY_LIB" "$ASSET_DIR" "$DEPLOY_MARKER" "$SERVICE" "$SERVICE_TMP"; do
    [ ! -L "$path" ] || fail "Refusing symlinked installation path: $path"
done
if [ -e "$DEPLOY_LIB" ] && [ ! -f "$DEPLOY_MARKER" ]; then
    fail "LaLune library exists without the deployment ownership marker; refusing to adopt it."
fi
if [ -e "$DEPLOY_MARKER" ]; then
    [ -f "$DEPLOY_MARKER" ] || fail "Ownership marker is not a regular file: $DEPLOY_MARKER"
    [ "$(cat "$DEPLOY_MARKER")" = "$MARKER_VALUE" ] || fail "Deployment ownership marker mismatch; refusing to overwrite deployment assets."
fi
for path in "$INSTALL" "$DEPLOY_MANAGER" "$SERVICE"; do
    if [ -e "$path" ] && [ ! -f "$DEPLOY_MARKER" ]; then
        fail "Existing target has no LaLune ownership marker; refusing to overwrite: $path"
    fi
    if [ -e "$path" ] && [ ! -f "$path" ]; then
        fail "Existing target is not a regular file: $path"
    fi
done

install -d -m 0755 /usr/local/bin /usr/local/lib
install -m 0755 "$BIN" "$INSTALL"
install -m 0755 "$BUNDLE_DIR/deploy-manager" "$DEPLOY_MANAGER"
install -d -m 0755 "$ASSET_DIR"
for asset in deploy-csqtt-lalune.sh csqtt-lalune-linux-arm64 csqtt-lalune-linux-amd64; do
    install -m 0755 "$BUNDLE_DIR/server-assets/$asset" "$ASSET_DIR/$asset"
done
printf '%s\n' "$MARKER_VALUE" > "$DEPLOY_MARKER"
chmod 0644 "$DEPLOY_MARKER"

# This backend is independent from the optional gateway service. Do not stop,
# mask, conflict with, or otherwise alter lalune-gateway.service.
cat > "$SERVICE_TMP" <<'UNIT'
[Unit]
Description=Original LaLune Linux backend (NanoPi ARM64)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
ExecStart=/usr/local/bin/lalune-backend
Restart=on-failure
RestartSec=3
Environment=RUST_LOG=info

[Install]
WantedBy=multi-user.target
UNIT
chmod 0644 "$SERVICE_TMP"
mv -f "$SERVICE_TMP" "$SERVICE"

systemctl daemon-reload
systemctl enable lalune-backend.service
if ! systemctl restart lalune-backend.service; then
    echo "LaLune backend failed to start; diagnostic output follows:" >&2
    systemctl status --no-pager --full lalune-backend.service >&2 || true
    journalctl -u lalune-backend.service -n 80 --no-pager >&2 || true
    exit 1
fi
if ! systemctl is-active --quiet lalune-backend.service; then
    echo "LaLune backend is not active after restart; diagnostic output follows:" >&2
    systemctl status --no-pager --full lalune-backend.service >&2 || true
    journalctl -u lalune-backend.service -n 80 --no-pager >&2 || true
    exit 1
fi

echo "LaLune backend installed and active. lalune-gateway.service was not modified."
