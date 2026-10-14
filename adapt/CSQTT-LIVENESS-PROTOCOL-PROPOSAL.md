# CSQTT authenticated liveness protocol — design gate

Status: proposal only; no wire behavior or production timeout has been changed.

## What the pinned sources establish

- The client receive loop awaits `TurnReceiver::recv()` without a session-level inactivity deadline.
- Server `SESSION_LEASE` is one-way today: it refreshes inbound activity and is then ignored. The pinned client has no matching lease sender/ack handler.
- Legacy all-`0xff` keepalives are ignored by the server without a response.
- `STREAM_ALIVE` belongs to the server's stream-repair round; it is not a periodic general session heartbeat.
- A blind receive-idle timeout can disconnect a healthy tunnel whose inbound traffic is quiet.

## Proposed wire behavior (requires review before implementation)

Use a new, versioned control message family; do not overload legacy `SESSION_LEASE` or `STREAM_ALIVE`.

1. **Capability negotiation.** The client advertises a liveness capability in an explicitly versioned registration extension. The server confirms the exact version in its authenticated configuration response. Absence of the extension/confirmation means legacy mode: do not start heartbeat deadlines and do not infer peer failure from idle receive.
2. **Challenge/response.** Once negotiated, the client sends an authenticated `PING` with a cryptographically random nonce and monotonic sequence. The server validates the negotiated session identity and returns an authenticated `PONG` echoing the nonce and sequence. Use the existing authenticated packet envelope; never accept an unwrapped control message as proof of life.
3. **Bounded state.** Permit at most one outstanding challenge per worker/session. Accept only the exact outstanding nonce/sequence; ignore duplicates, stale replies and unsolicited replies. Rotate nonce for each challenge. Do not let an old response satisfy a newer challenge.
4. **Timeout policy.** A missed response marks the session suspect, not immediately dead. Use a bounded number of consecutive misses and a grace period informed by the selected TURN transport. On confirmed failure, return a typed liveness error through the existing reader/session teardown path so the existing worker supervisor owns retry and cleanup. Do not spawn replacement workers from the heartbeat task.
5. **Idle correctness.** Schedule probes independently of TUN payload traffic. A healthy quiet tunnel must remain connected when each valid PONG arrives. Normal user traffic may count as liveness only if the protocol explicitly defines it and safely correlates it to the current session; otherwise keep the control exchange explicit.
6. **Compatibility.** New client + old server: negotiation fails closed to legacy behavior (no heartbeat timeout). Old client + new server: server ignores unknown versioned controls safely. Only after negotiation succeeds may either side rely on liveness messages. Never infer support solely from a version string not covered by the wire-protocol compatibility rules.

## Security and implementation questions to settle

- Define exact binary encoding and maximum lengths; reject malformed lengths, unknown mandatory flags and integer overflow.
- Ensure PING/PONG are protected by the same inbound authentication and replay window as other packets. Add a per-session sequence/nonce check to prevent replay even inside the accepted replay window.
- Decide whether probe state belongs to each TURN allocation, each worker, or the shared device session. The current recovery evidence is per worker, so the initial implementation should be per worker unless code review proves another scope correct.
- Ensure pending timers and sends are cancellation-aware; session teardown must cancel the liveness task and not leak a worker or TURN allocation.
- Consider UDP loss, reordering, delayed packets, server overload, TURN refresh behavior and clock jumps. Use monotonic time only for deadlines.
- Keep `vk_hash_mode` and `vk_auth_mode` separate. This E2E uses a disposable TURN fixture and does not prove VK auth compatibility.

## Required test matrix before enabling

1. Negotiated client/server, quiet tunnel for several probe periods: remains connected.
2. Valid PONG with exact nonce/sequence: resets miss count.
3. Missing PONG: only fails after the documented bounded miss policy.
4. Wrong nonce, stale sequence, duplicate PONG, malformed PONG and unauthenticated PONG: none can satisfy a challenge.
5. Delayed/reordered PONG and packet loss: no premature reconnect; eventual recovery after real server restart.
6. Server restart while traffic is active and while tunnel is idle: same client process re-registers all nine workers and restores bidirectional TUN traffic.
7. New client with old server and old client with new server: no heartbeat-induced reconnect loop.
8. Cancellation during pending probe: all tasks/allocations are cleaned up; no duplicate worker registrations.
9. Repeat E2E with stock (unmodified) receive loop and with liveness feature explicitly negotiated. The current test-only idle watchdog must not count as proof of this protocol.
10. Verify packaged artifact provenance before claiming the deployed ARM64 binary includes the fix.

## Current gate

Do not change the packaged runtime artifact, deployment workflows, production services, or device network configuration. Implement the protocol only in disposable pinned-source checkouts after exact wire encoding and compatibility behavior are agreed and tests can cover both endpoints. The current E2E watchdog remains a diagnostic fixture only.
