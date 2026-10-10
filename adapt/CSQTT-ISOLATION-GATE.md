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

## Current CI status and next end-to-end gate

- CI run #352 (commit `cf201e2`) passed in a disposable ARM64 system VM. It proved that the packaged ARM64 server answers a pinned, encrypted upstream `GETCONF` fixture with a protocol response and that install/uninstall preserves the simulated pre-existing services and main routes.
- This is **not** proof of client-side `TUNCONF` handling or real IP packet delivery through the TUN dataplane. The test fixture currently validates only the encrypted setup request/response at UDP level.
- Before enabling deployment, extend the VM test to seed a disposable device/password configuration, assert a decoded `TUNCONF` containing the expected test IP/DNS, and then run a two-ended data-plane test that sends a known IP packet through an authenticated CSQTT session and verifies delivery on the opposite TUN/UDP endpoint. The test must fail if it merely observes an open port or a non-empty encrypted response.
- NanoPi installation remains unauthorized and must not be attempted as part of these CI steps.
