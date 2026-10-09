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

1. Build a LaLune-specific server asset from the pinned v2.1.9 source with a dedicated TUN interface (for example `csqtt-lalune0`) and a dedicated tunnel subnet. Verify every TUN and network setup reference is parameterized or renamed.
2. Write a separate installer; do not invoke the upstream `deploy.sh install` or `uninstall`.
3. Keep all persistent data and helpers under `/etc/csqtt-lalune`, `/var/lib/csqtt-lalune`, `/var/log/csqtt-lalune`, and `/usr/local/lib/csqtt-lalune`; use `csqtt-lalune.service` and uniquely named helper/timer units.
4. Use UDP 47000 and web 47002. Before changes, fail closed if either port is occupied or any LaLune-owned resource has an unexpected type/content. Never kill arbitrary port holders.
5. Use uniquely named nftables tables/chains and only remove those exact owned objects on uninstall. Do not flush shared tables or remove generic CSQTT rules.
6. Avoid global sysctl edits where possible. If a sysctl change is required, track the prior value and restore it only if the current value still equals the value LaLune set.
7. Add CI tests for generated service, paths, TUN/subnet, firewall ownership, preflight refusal, install idempotency, and uninstall isolation. Scan the generated installer for forbidden global paths and upstream installer invocation.
8. Audit the packaged artifact and test install/uninstall in a disposable ARM64 VM/container with a simulated pre-existing Android/production CSQTT service before authorizing NanoPi installation.

## Safety invariant

Until every item above passes, the DeployManager must refuse deployment and uninstallation without making remote changes. Existing CSQTT services, Android CSQTT, production routing, HydraRoute, and Tailscale are out of scope and must remain untouched.
