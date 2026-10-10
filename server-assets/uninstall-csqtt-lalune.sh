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
[[ -f "$UNIT_FILE" ]] || die "our service unit is absent; refusing broad cleanup"
grep -Fq 'Description=CSQTT LaLune isolated dataplane' "$UNIT_FILE" || die "service unit is not ours"
[[ -f "$ETC/.managed-by-lalune" && "$(cat "$ETC/.managed-by-lalune")" == "$MARKER" ]] || die "config ownership marker missing or invalid"
[[ -f "$LIB/.managed-by-lalune" && "$(cat "$LIB/.managed-by-lalune")" == "$MARKER" ]] || die "binary directory ownership marker missing or invalid"

systemctl disable --now "$UNIT" || die "could not stop/disable our service; preserving all files"
systemctl reset-failed "$UNIT" >/dev/null 2>&1 || true
rm -f -- "$UNIT_FILE"
rm -f -- "$BIN"
rm -rf -- "$LIB"
systemctl daemon-reload
# Configuration, credentials, state and logs are deliberately preserved.
# --purge is a separate, explicit opt-in and still validates ownership markers.
if [[ "${1:-}" == "--purge" ]]; then
  [[ -f "$ETC/.managed-by-lalune" && "$(cat "$ETC/.managed-by-lalune")" == "$MARKER" ]] || die "config ownership marker changed; not purging"
  rm -rf -- "$ETC" "$STATE" "$LOG"
elif [[ $# -gt 0 ]]; then
  die "unknown argument: $1"
fi
echo "CSQTT_LALUNE_UNINSTALL_OK"
