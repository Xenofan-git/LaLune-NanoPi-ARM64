#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

# Dedicated installer for the patched CSQTT v2.1.9 LaLune dataplane.
# Never invokes upstream deploy.sh. It owns only explicitly named LaLune paths.
readonly UNIT="csqtt-lalune.service"
readonly BIN="/usr/local/bin/csqtt-lalune"
readonly LIB="/usr/local/lib/csqtt-lalune"
readonly ETC="/etc/csqtt-lalune"
readonly STATE="/var/lib/csqtt-lalune"
readonly LOG="/var/log/csqtt-lalune"
readonly UNIT_FILE="/etc/systemd/system/csqtt-lalune.service"
readonly MARKER="CSQTT-LALUNE-MANAGED-V1"
readonly UDP_PORT="47000"
readonly WEB_PORT="47002"

die(){ echo "csqtt-lalune install: $*" >&2; exit 1; }
[[ ${EUID} -eq 0 ]] || die "run as root"
[[ "$(uname -s)" == Linux ]] || die "Linux is required"
[[ "$(uname -m)" == aarch64 || "$(uname -m)" == arm64 ]] || die "this package targets ARM64; found $(uname -m)"

HERE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
SOURCE="${HERE}/csqtt-lalune-linux-arm64"
[[ -s "$SOURCE" ]] || die "missing isolated binary: $SOURCE"
command -v systemctl >/dev/null 2>&1 || die "systemd is required"
command -v ss >/dev/null 2>&1 || die "ss is required for safe port preflight"

# Never adopt or overwrite another service or an unowned path.
if [[ -e "$UNIT_FILE" ]] && ! grep -Fq 'Description=CSQTT LaLune isolated dataplane' "$UNIT_FILE"; then
  die "$UNIT_FILE already exists and is not our service"
fi
if [[ -e "$ETC" ]]; then
  [[ -f "$ETC/.managed-by-lalune" ]] || die "$ETC exists without our ownership marker; refusing to adopt it"
  [[ "$(cat "$ETC/.managed-by-lalune")" == "$MARKER" ]] || die "ownership marker mismatch"
fi
if [[ -e "$BIN" && ! -e "$UNIT_FILE" ]]; then
  die "$BIN exists without our service unit; refusing to overwrite"
fi
if [[ -e "$LIB" && ! -f "$LIB/.managed-by-lalune" ]]; then
  die "$LIB exists without our ownership marker; refusing to overwrite"
fi

# If our service is already installed, stop it only after verifying its identity.
if [[ -e "$UNIT_FILE" ]]; then
  systemctl stop "$UNIT" || die "could not stop our existing service"
fi

# Do not kill listeners. If either port is occupied, leave the host unchanged.
if ss -H -lun "sport = :$UDP_PORT" | grep -q .; then
  if ! systemctl is-active --quiet "$UNIT"; then die "UDP port $UDP_PORT is occupied by another process"; fi
fi
if ss -H -ltn "sport = :$WEB_PORT" | grep -q .; then
  die "TCP port $WEB_PORT is occupied; no listener will be killed"
fi

install -d -m 0750 "$ETC" "$STATE" "$LOG" "$LIB"
printf '%s\n' "$MARKER" > "$ETC/.managed-by-lalune"
printf '%s\n' "$MARKER" > "$LIB/.managed-by-lalune"
install -m 0755 "$SOURCE" "${BIN}.new"
mv -f -- "${BIN}.new" "$BIN"

# Keep configuration and state in LaLune-only directories. No global sysctl,
# firewall chain, main route table, generic csqtt path, or upstream installer.
cat > "${UNIT_FILE}.new" <<'UNIT'
[Unit]
Description=CSQTT LaLune isolated dataplane
Documentation=https://github.com/Xenofan-git/LaLune-NanoPi-ARM64
After=network-online.target
Wants=network-online.target
ConditionPathIsExecutable=/usr/local/bin/csqtt-lalune

[Service]
Type=simple
ExecStart=/usr/local/bin/csqtt-lalune --listen 0.0.0.0:47000 --web-port 47002 --config-dir /etc/csqtt-lalune
Restart=on-failure
RestartSec=3
UMask=0077
LimitNOFILE=65536
# CSQTT needs root for its dedicated TUN and namespaced policy rules.
User=root
Group=root
NoNewPrivileges=false
PrivateTmp=true
ProtectHome=true
ProtectSystem=full
ReadWritePaths=/etc/csqtt-lalune /var/lib/csqtt-lalune /var/log/csqtt-lalune /run
[Install]
WantedBy=multi-user.target
UNIT
chmod 0644 "${UNIT_FILE}.new"
mv -f -- "${UNIT_FILE}.new" "$UNIT_FILE"
systemctl daemon-reload
systemctl enable "$UNIT" >/dev/null
systemctl start "$UNIT" || {
  systemctl --no-pager --full status "$UNIT" >&2 || true
  die "service failed to start; LaLune files were retained for diagnosis"
}
systemctl is-active --quiet "$UNIT" || die "service is not active"
echo "CSQTT_LALUNE_INSTALL_OK"
