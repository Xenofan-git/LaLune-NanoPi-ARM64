# LaLune CSQTT isolation gate

Status: deployment is intentionally disabled. This file is a checklist for the dedicated installer; it is not permission to deploy.

## Verified upstream v2.1.9 constraints

The server binary has configurable UDP listen address, web port, and config directory, but its TUN interface is compiled as the constant `csqtt1` in both `rust-server/net_setup.rs` and `rust-server/tun_device.rs`. Changing only CLI ports/configuration therefore does **not** isolate the network dataplane.

The upstream installer `app/src/main/assets/deploy.sh` also owns shared global resources including:

- `/etc/csqtt`, `/usr/local/bin/csqtt`, `/usr/local/lib/csqtt`, and `/run/csqtt`;
- `csqtt.service`, `csqtt-letsencrypt.service/timer`, and Docker container/image `csqtt`;
- fixed TUN `csqtt1`, global sysctl files, and firewall/NAT rules;
- global log, upload, certificate-renewal and helper paths.

Changing peer/web ports and config directory alone is not sufficient. In particular, an installer or uninstaller must never call the upstream install/uninstall entry points on a host that may already run Android or production CSQTT.

## Required implementation before deployment can be enabled

1. Build a LaLune-specific server asset from the pinned v2.1.9 source with a dedicated TUN interface (`csqtt-lalune0`) and tunnel subnet (`10.67.68.0/24`). Namespace the proxy-routing policy table/priority, packet marks, and every iptables comment used for cleanup/watchdog; verify the server cannot delete another CSQTT instance's rules or flush a shared policy table. CI must test these source invariants and run the ARM64 binary's `--help` under QEMU.
2. A first dedicated installer/uninstaller pair now exists at `server-assets/install-csqtt-lalune.sh` and `server-assets/uninstall-csqtt-lalune.sh`. They do not invoke upstream `deploy.sh`, use ownership markers and isolated paths, preflight ports without killing listeners, and preserve config/state by default. This item is **implemented but not yet validated end-to-end**; DeployManager remains fail-closed and does not invoke these scripts yet.
3. Keep all persistent data and helpers under `/etc/csqtt-lalune`, `/var/lib/csqtt-lalune`, `/var/log/csqtt-lalune`, and `/usr/local/lib/csqtt-lalune`; use `csqtt-lalune.service` and uniquely named helper/timer units.
4. Use UDP 47000 and web 47002. Before changes, fail closed if either port is occupied or any LaLune-owned resource has an unexpected type/content. Never kill arbitrary port holders.
5. Use uniquely named firewall tables/chains and uniquely marked rules; remove only exact LaLune-owned objects on uninstall. The current upstream runtime uses iptables and policy routing, so its cleanup markers, rule priorities, marks, and route tables must be LaLune-specific. Never flush shared tables or remove generic CSQTT rules.
6. Avoid global sysctl edits where possible. If a sysctl change is required, track the prior value and restore it only if the current value still equals the value LaLune set.
7. Add CI tests for generated service, paths, TUN/subnet, firewall ownership, preflight refusal, install idempotency, and uninstall isolation. Scan the generated installer for forbidden global paths and upstream installer invocation.
8. Audit the packaged artifact and test install/uninstall in a disposable ARM64 VM/container with a simulated pre-existing Android/production CSQTT service before authorizing NanoPi installation.

## Safety invariant

Until every item above passes, the DeployManager must refuse deployment and uninstallation without making remote changes. The new scripts are packaged candidates only; they are not authorization to run them on NanoPi. Existing CSQTT services, Android CSQTT, production routing, HydraRoute, and Tailscale are out of scope and must remain untouched.

## Protocol trace for the next test

The pinned v2.1.9 source trace identifies why the current UDP fixture cannot establish tunnel readiness:

- The existing pinned wire fixture is a legacy `CSQTT-WIRE-2` first-stage setup request. It proves credential decryption/session creation, but does not complete the client's current configuration exchange.
- The client builds the follow-up request as `GETCONF:<local_port>|<device_id>|<password>|<generation_id>|<salt>|<worker_id>|<desired_stream_count>|CSQTT-WIRE-3`.
- The server's configuration handler validates that request, allocates or resolves the device IP, then returns `TUNCONF:<device_ip>:<dns>:<client_port>:stream-v2` (or a denial/no-config response). The server's TUNCONF response must be decoded with the established session's actual packet keys; checking raw UDP bytes for the string would be invalid.
- The client implementation is in upstream `rust-client/protocol.rs`, `rust-client/session.rs`, and `rust-client/wrap.rs`. The next harness should reuse those real protocol functions or equivalent server test helpers, not invent encryption or hard-code an encrypted response.
- Only after authenticated configuration is decoded should a second test inject a valid IPv4 packet through the isolated TUN and assert it arrives at the authenticated opposite endpoint. The test must also assert that unrelated main routes and the three production-like services remain unchanged.

This trace is analysis of pinned source, not a passing TUNCONF/data-plane test. No deployment authorization is implied.

## Current CI status and next end-to-end gate

- CI run #352 (commit `cf201e2`) passed in a disposable ARM64 system VM. It proved that the packaged ARM64 server answers a pinned, encrypted upstream `GETCONF` fixture with a protocol response and that install/uninstall preserves the simulated pre-existing services and main routes.
- This is **not** proof of client-side `TUNCONF` handling or real IP packet delivery through the TUN dataplane. The test fixture currently validates only the encrypted setup request/response at UDP level.
- Before enabling deployment, extend the VM test to seed a disposable device/password configuration, assert a decoded `TUNCONF` containing the expected test IP/DNS, and then run a two-ended data-plane test that sends a known IP packet through an authenticated CSQTT session and verifies delivery on the opposite TUN/UDP endpoint. The test must fail if it merely observes an open port or a non-empty encrypted response.
- NanoPi installation remains unauthorized and must not be attempted as part of these CI steps.

## Comparative source audit (2026-10-10)

Pinned references used for comparison:

- LaLune desktop Linux implementation: `Endlad2/LaLune@e4a6d08b63aef6025bf8ad8f77da660ea552e04b`, file `Desktop/Linux/app_linux.go`.
- CSQTT server: `amurcanov/csqtt@v2.1.9`, files `app/src/main/assets/deploy.sh`, `rust-server/net_setup.rs`, `rust-server/tun_device.rs`, and `rust-server/protocol.rs`.
- Integration patcher: `adapt/patch-csqtt-lalune-source.py` in this repository.

### Confirmed differences

1. Original LaLune Linux client creates `csqtt0`, appends DNS servers to the host `/etc/resolv.conf`, and installs `default dev csqtt0`. That behavior must not be copied into the NanoPi gateway path: it changes host-wide routing/DNS rather than confining client traffic to a dedicated policy route.
2. Original CSQTT v2.1.9 server hard-codes `csqtt1`, `10.66.67.1`, and `10.66.67.0/24` across more than one Rust module. The integration patcher changes both TUN definitions, the subnet prefix used by the route table, model-side subnet references, and protocol test fixtures; changing only `net_setup.rs` would be incomplete.
3. The upstream proxy-routing module uses fixed policy table/priority values, packet marks, and iptables comments. The patcher assigns LaLune-specific values (`47001`, `47066`, `0x6741`, `0x6742`) and LaLune-prefixed comments, and removes global `ip route flush cache` operations. This is a source-level adaptation; runtime ownership behavior still requires behavioral tests.
4. The original server's configuration protocol and the current VM smoke test are different levels of validation. The VM sends the pinned legacy `CSQTT-WIRE-2` fixture and checks only that the server returns at least 32 bytes. It does not prove the current `CSQTT-WIRE-3` configuration request, authenticated `TUNCONF` decoding, or IP packet forwarding.

### Newly explicit acceptance tests still required

- Run the upstream Rust unit tests against the patched server source (including protocol/configuration tests) and verify the subnet-related tests have been adapted rather than silently skipped.
- Add a test that demonstrates the current client configuration request is accepted and that the response is decoded into the expected test IP/DNS using the real session keys.
- Add a two-ended test that sends a valid IPv4 packet through an authenticated session and observes the same packet at the intended peer TUN/UDP endpoint.
- Verify route-rule/firewall cleanup by comparing exact pre-existing entries before and after start/stop, including an adversarial rule with a similar but non-identical comment. Text grep checks alone are not sufficient.
- Keep the deployment gate closed until these tests pass. Do not run the package on NanoPi as part of this audit.
