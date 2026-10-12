#!/usr/bin/env bash
set -Eeuo pipefail
umask 077
readonly UNIT="csqtt-lalune.service"
readonly BIN="/usr/local/bin/csqtt-lalune"
readonly LIB="/usr/local/lib/csqtt-lalune"
readonly ETC="/etc/csqtt-lalune"
readonly STATE="/var/lib/csqtt-lalune"
readonly LOG="/var/log/csqtt-lalune"
readonly UNIT_FILE="/etc/systemd/system/csqtt-lalune.service"
readonly MARKER="CSQTT-LALUNE-MANAGED-V1"
die(){ echo "csqtt-lalune uninstall: $*" >&2; exit 1; }
[[ ${EUID} -eq 0 ]] || die "run as root"
if [[ $# -gt 1 || ( $# -eq 1 && "${1}" != "--purge" ) ]]; then die "usage: $0 [--purge]"; fi
# Do not follow ownership markers through symlinks; all cleanup targets must be real paths.
for owned_path in "$UNIT_FILE" "$BIN" "$LIB" "$ETC" "$STATE" "$LOG"; do
  [[ ! -L "$owned_path" ]] || die "$owned_path is a symlink; refusing cleanup"
done
[[ -f "$UNIT_FILE" ]] || die "our service unit is absent; refusing broad cleanup"
grep -Fq 'Description=CSQTT LaLune isolated dataplane' "$UNIT_FILE" || die "service unit is not ours"
[[ -f "$ETC/.managed-by-lalune" && ! -L "$ETC/.managed-by-lalune" && "$(cat "$ETC/.managed-by-lalune")" == "$MARKER" ]] || die "config ownership marker missing or invalid"
[[ -f "$LIB/.managed-by-lalune" && ! -L "$LIB/.managed-by-lalune" && "$(cat "$LIB/.managed-by-lalune")" == "$MARKER" ]] || die "binary directory ownership marker missing or invalid"
[[ -f "$STATE/.managed-by-lalune" && ! -L "$STATE/.managed-by-lalune" && "$(cat "$STATE/.managed-by-lalune")" == "$MARKER" ]] || die "state ownership marker missing or invalid"
[[ -f "$LOG/.managed-by-lalune" && ! -L "$LOG/.managed-by-lalune" && "$(cat "$LOG/.managed-by-lalune")" == "$MARKER" ]] || die "log ownership marker missing or invalid"

systemctl disable --now "$UNIT" || die "could not stop/disable our service; preserving all files"
command -v ip >/dev/null 2>&1 || die "iproute2 missing; preserving binary and service unit for manual cleanup"
command -v iptables-save >/dev/null 2>&1 || die "iptables-save missing; preserving binary and service unit for manual cleanup"
if ip link show dev csqtt-lalune0 >/dev/null 2>&1; then die "csqtt-lalune0 remains after stop; preserving binary and service unit"; fi
RULES="$(ip -4 rule show)"
if printf '%s\n' "$RULES" | grep -Eq '(^|[[:space:]])(47001|47066):|fwmark (0x6741|0x6742)(/|[[:space:]])|lookup (47001|47066)([[:space:]]|$)'; then die "LaLune policy rules remain after stop; preserving binary and service unit"; fi
if [[ -n "$(ip -4 route show table 47001 2>/dev/null)" || -n "$(ip -4 route show table 47066 2>/dev/null)" ]]; then die "LaLune route table entries remain after stop; preserving binary and service unit"; fi
if iptables-save 2>/dev/null | grep -Fq 'CSQTT_LALUNE_'; then die "LaLune firewall rules remain after stop; preserving binary and service unit"; fi
systemctl reset-failed "$UNIT" >/dev/null 2>&1 || true
rm -f -- "$UNIT_FILE"
rm -f -- "$BIN"
rm -rf -- "$LIB"
systemctl daemon-reload
# Configuration, credentials, state and logs are deliberately preserved.
# --purge is a separate, explicit opt-in and still validates ownership markers.
if [[ "${1:-}" == "--purge" ]]; then
  rm -rf -- "$ETC" "$STATE" "$LOG"
fi
echo "CSQTT_LALUNE_UNINSTALL_OK"
