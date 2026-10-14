#!/usr/bin/env bash
# Runs only inside the disposable ARM64 system VM created by the CI workflow.
# Requires the experimental patched Rust client/server and the TUN bridge script.
set -euo pipefail

CLIENT="${1:-/home/tester/csqtt-client-arm64-liveness-experimental}"
SERVER="${2:-/home/tester/csqtt-server-arm64-liveness-experimental}"
BRIDGE="${3:-/home/tester/csqtt-test-tun-udp-bridge.py}"
ROOT=/tmp/csqtt-arm64-liveness-vm
SERVER_NS=csqtt-arm64-server
CLIENT_NS=csqtt-arm64-client
mkdir -p "$ROOT"
SERVER_LOG="$ROOT/server.log"
CLIENT_LOG="$ROOT/client.log"
TURN_LOG="$ROOT/turn.log"
BRIDGE_LOG="$ROOT/bridge.log"
COUNTER="$ROOT/tunconf-counter.log"
: > "$SERVER_LOG"; : > "$CLIENT_LOG"; : > "$TURN_LOG"; : > "$BRIDGE_LOG"; : > "$COUNTER"

server_pid=
client_pid=
turn_pid=
bridge_pid=
cleanup() {
  for pid in "$bridge_pid" "$client_pid" "$server_pid" "$turn_pid"; do
    [ -z "$pid" ] || { kill "$pid" 2>/dev/null || true; wait "$pid" 2>/dev/null || true; }
  done
  ip netns del "$CLIENT_NS" 2>/dev/null || true
  ip netns del "$SERVER_NS" 2>/dev/null || true
}
trap cleanup EXIT

test "$(uname -m)" = aarch64
test -x "$CLIENT"; test -x "$SERVER"; test -s "$BRIDGE"
test "$("$SERVER" --protocol-revision)" = CSQTT-WIRE-4
if "$CLIENT" >"$ROOT/client-cli-smoke.log" 2>&1; then
  echo "client unexpectedly accepted missing arguments" >&2
  exit 1
fi
grep -Fq 'Нужны -peer и хеши VK' "$ROOT/client-cli-smoke.log"

ip netns del "$CLIENT_NS" 2>/dev/null || true
ip netns del "$SERVER_NS" 2>/dev/null || true
ip netns add "$SERVER_NS"
ip netns add "$CLIENT_NS"
ip link add csqtt-vs0 type veth peer name csqtt-vc0
ip link set csqtt-vs0 netns "$SERVER_NS"
ip link set csqtt-vc0 netns "$CLIENT_NS"
ip -n "$SERVER_NS" link set lo up
ip -n "$SERVER_NS" addr add 10.200.0.1/24 dev csqtt-vs0
ip -n "$SERVER_NS" link set csqtt-vs0 up
ip -n "$CLIENT_NS" link set lo up
ip -n "$CLIENT_NS" addr add 10.200.0.2/24 dev csqtt-vc0
ip -n "$CLIENT_NS" link set csqtt-vc0 up
ip netns exec "$CLIENT_NS" ping -c 1 -W 3 10.200.0.1 >/dev/null

ip netns exec "$SERVER_NS" turnserver -n --listening-ip=10.200.0.1 --relay-ip=10.200.0.1 \
  --listening-port=3478 --min-port=49160 --max-port=49200 \
  --realm=ci.test --user=ci-e2e-user:ci-e2e-turn-password \
  --lt-cred-mech --fingerprint --no-cli --no-tls --no-dtls --log-file="$TURN_LOG" &
turn_pid=$!
for attempt in $(seq 1 40); do
  kill -0 "$turn_pid" 2>/dev/null || { cat "$TURN_LOG" >&2; exit 1; }
  grep -Eqi 'listener address.*10\.200\.0\.1|listening.*3478' "$TURN_LOG" && break
  sleep 0.5
done

start_server() {
  local previous_count
  previous_count=$(grep -Fc 'RTP AEAD: 10.200.0.1:46000' "$SERVER_LOG" || true)
  ip netns exec "$SERVER_NS" "$SERVER" --listen 10.200.0.1:46000 --web-port 0 \
    --config-dir "$ROOT/server-config" --password ci-e2e-password \
    --device-id ci-e2e-device --web-pass ci-e2e-web-password >>"$SERVER_LOG" 2>&1 &
  server_pid=$!
  local ready=0
  for attempt in $(seq 1 60); do
    local current_count
    current_count=$(grep -Fc 'RTP AEAD: 10.200.0.1:46000' "$SERVER_LOG" || true)
    if [ "$current_count" -gt "$previous_count" ]; then ready=1; break; fi
    if ! kill -0 "$server_pid" 2>/dev/null; then tail -n 100 "$SERVER_LOG" >&2; exit 1; fi
    sleep 0.5
  done
  [ "$ready" -eq 1 ] || { tail -n 100 "$SERVER_LOG" >&2; echo "ARM64 server did not announce a fresh ready event" >&2; exit 1; }
}
start_server

ip netns exec "$CLIENT_NS" env \
  CSQTT_TEST_TURN_USERNAME=ci-e2e-user \
  CSQTT_TEST_TURN_PASSWORD=ci-e2e-turn-password \
  CSQTT_TEST_TURN_SERVER=10.200.0.1 \
  CSQTT_TEST_TUNCONF_COUNTER_FILE="$COUNTER" \
  "$CLIENT" --peer 10.200.0.1:46000 --turn 10.200.0.1 --port 3478 \
  --vk ci-e2e-hash --vk-hash-mode manual --vk-auth-mode vkcalls \
  --password ci-e2e-password --device-id ci-e2e-device \
  --workers 9 --listen 127.0.0.1:9000 --turn-transport udp >"$CLIENT_LOG" 2>&1 &
client_pid=$!
for attempt in $(seq 1 90); do
  if grep -Fq '[КЛИЕНТ] Tunnel IP:' "$CLIENT_LOG" && grep -Fq -- '-> TUNCONF' "$SERVER_LOG"; then break; fi
  if ! kill -0 "$client_pid" 2>/dev/null; then tail -n 120 "$CLIENT_LOG" "$SERVER_LOG" >&2; exit 1; fi
  sleep 1
done
grep -Fq '[КЛИЕНТ] Tunnel IP:' "$CLIENT_LOG" || { tail -n 120 "$CLIENT_LOG" "$SERVER_LOG" >&2; exit 1; }
grep -Fq -- '-> TUNCONF' "$SERVER_LOG" || { tail -n 120 "$CLIENT_LOG" "$SERVER_LOG" >&2; exit 1; }

ip netns exec "$CLIENT_NS" env CSQTT_TEST_CLIENT_LISTEN=127.0.0.1 CSQTT_TEST_CLIENT_PORT=9000 \
  python3 "$BRIDGE" >"$BRIDGE_LOG" 2>&1 &
bridge_pid=$!
for attempt in $(seq 1 40); do
  grep -Fq CSQTT_TEST_TUN_BRIDGE_READY "$BRIDGE_LOG" && break
  if ! kill -0 "$bridge_pid" 2>/dev/null; then cat "$BRIDGE_LOG" >&2; exit 1; fi
  sleep 0.25
done
grep -Fq CSQTT_TEST_TUN_BRIDGE_READY "$BRIDGE_LOG"
ip -n "$CLIENT_NS" addr add 10.66.67.2/32 dev csqtt-client0
ip -n "$CLIENT_NS" link set csqtt-client0 mtu 1300 up
ip -n "$CLIENT_NS" route replace 10.66.67.1/32 dev csqtt-client0

echo "ARM64_LIVENESS_VM: bidirectional dataplane before restart"
ip netns exec "$CLIENT_NS" ping -I csqtt-client0 -c 3 -W 3 10.66.67.1 | tee "$ROOT/ping-before.log"
grep -Eq '0% packet loss|0 packets lost' "$ROOT/ping-before.log"

# Keep the TUN payload idle for multiple five-second liveness periods.
before_quiet=$(grep -Fc -- '-> TUNCONF' "$SERVER_LOG" || true)
sleep 22
kill -0 "$client_pid"
quiet_after=$(grep -Fc -- '-> TUNCONF' "$SERVER_LOG" || true)
test "$quiet_after" -eq "$before_quiet" || {
  echo "TUNCONF changed during healthy quiet interval; inspect client/server logs" >&2
  tail -n 120 "$CLIENT_LOG" "$SERVER_LOG" >&2
  exit 1
}
echo "ARM64_LIVENESS_VM: quiet tunnel survived multiple negotiated PING/PONG periods"

client_pid_before=$client_pid
server_before=$(grep -Fc -- '-> TUNCONF' "$SERVER_LOG" || true)
client_before=$(grep -Fc 'TUNCONF' "$COUNTER" || true)
ready_before=$(grep -Fc '[READY] Поток готов' "$CLIENT_LOG" || true)
old_server_pid=$server_pid
kill "$old_server_pid"
wait "$old_server_pid" 2>/dev/null || true
server_pid=
if kill -0 "$old_server_pid" 2>/dev/null; then
  echo "old server process survived termination" >&2
  exit 1
fi
for attempt in $(seq 1 8); do
  kill -0 "$client_pid" || { tail -n 120 "$CLIENT_LOG" >&2; exit 1; }
  sleep 0.25
done
start_server

recovered=0
for attempt in $(seq 1 100); do
  kill -0 "$client_pid" || { tail -n 120 "$CLIENT_LOG" >&2; exit 1; }
  server_now=$(grep -Fc -- '-> TUNCONF' "$SERVER_LOG" || true)
  client_now=$(grep -Fc 'TUNCONF' "$COUNTER" || true)
  ready_now=$(grep -Fc '[READY] Поток готов' "$CLIENT_LOG" || true)
  if [ "$((server_now-server_before))" -ge 9 ] && [ "$((client_now-client_before))" -ge 9 ] && [ "$((ready_now-ready_before))" -ge 9 ]; then
    recovered=1; break
  fi
  sleep 1
done
if [ "$recovered" -ne 1 ]; then
  echo "ARM64 recovery counts: server=$((server_now-server_before)) client=$((client_now-client_before)) ready=$((ready_now-ready_before))" >&2
  tail -n 160 "$CLIENT_LOG" "$SERVER_LOG" "$TURN_LOG" "$BRIDGE_LOG" >&2
  exit 1
fi
test "$client_pid" = "$client_pid_before"
kill -0 "$client_pid"

echo "ARM64_LIVENESS_VM: bidirectional dataplane after restart"
ip netns exec "$CLIENT_NS" ping -I csqtt-client0 -c 3 -W 3 10.66.67.1 | tee "$ROOT/ping-after.log"
grep -Eq '0% packet loss|0 packets lost' "$ROOT/ping-after.log"
echo "CSQTT_EXPERIMENTAL_ARM64_VM_LIVENESS_TUN_RECOVERY_PASS"
echo "--- CLIENT LOG TAIL ---"; tail -n 80 "$CLIENT_LOG"
echo "--- SERVER LOG TAIL ---"; tail -n 80 "$SERVER_LOG"
