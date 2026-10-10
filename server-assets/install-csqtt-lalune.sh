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
command -v ip >/dev/null 2>&1 || die "iproute2 is required for safe route/interface preflight"
command -v iptables-save >/dev/null 2>&1 || die "iptables is required for safe firewall preflight"

# Reject symlinks before checking ownership markers or writing anything. A marker
# reachable through a symlink does not make the external target LaLune-owned.
for owned_path in "$UNIT_FILE" "$BIN" "$LIB" "$ETC" "$STATE" "$LOG"; do
  [[ ! -L "$owned_path" ]] || die "$owned_path is a symlink; refusing to follow or replace it"
done

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
for owned_dir in "$STATE" "$LOG"; do
  if [[ -e "$owned_dir" ]]; then
    [[ -f "$owned_dir/.managed-by-lalune" ]] || die "$owned_dir exists without our ownership marker; refusing to adopt it"
    [[ "$(cat "$owned_dir/.managed-by-lalune")" == "$MARKER" ]] || die "$owned_dir ownership marker mismatch"
  fi
done

# Never stop a running service automatically: a preflight failure must not
# interrupt an already working instance. Upgrades require an explicit stop by
# the operator after checking the maintenance window.
if [[ -e "$UNIT_FILE" ]] && systemctl is-active --quiet "$UNIT"; then
  die "$UNIT is already active; stop it deliberately before replacing the binary"
fi

# Do not kill listeners. Preflight both ports before making any filesystem changes.
if ss -H -lun "sport = :$UDP_PORT" | grep -q .; then
  die "UDP port $UDP_PORT is occupied; no listener will be killed"
fi
if ss -H -ltn "sport = :$WEB_PORT" | grep -q .; then
  die "TCP port $WEB_PORT is occupied; no listener will be killed"
fi
if ip link show dev csqtt-lalune0 >/dev/null 2>&1; then
  die "csqtt-lalune0 already exists; refusing to adopt or reconfigure an existing interface"
fi
RULES="$(ip -4 rule show)"
if printf '%s\n' "$RULES" | grep -Eq '(^|[[:space:]])(47001|47066):|fwmark (0x6741|0x6742)(/|[[:space:]])|lookup (47001|47066)([[:space:]]|$)'; then
  die "LaLune policy identifiers already exist; refusing to delete or reuse existing rules"
fi
if [[ -n "$(ip -4 route show table 47001 2>/dev/null)" || -n "$(ip -4 route show table 47066 2>/dev/null)" ]]; then
  die "LaLune route table 47001/47066 is non-empty; refusing to flush or adopt it"
fi
if iptables-save 2>/dev/null | grep -Fq 'CSQTT_LALUNE_'; then
  die "LaLune firewall markers already exist; refusing to adopt or clean up existing rules"
fi

install -d -m 0750 "$ETC" "$STATE" "$LOG" "$LIB"
printf '%s\n' "$MARKER" > "$ETC/.managed-by-lalune"
printf '%s\n' "$MARKER" > "$LIB/.managed-by-lalune"
printf '%s\n' "$MARKER" > "$STATE/.managed-by-lalune"
printf '%s\n' "$MARKER" > "$LOG/.managed-by-lalune"
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
