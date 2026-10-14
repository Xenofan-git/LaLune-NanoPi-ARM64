# CSQTT-LaLune installer contract

These scripts install only the separately patched CSQTT v2.1.9 LaLune dataplane, with ARM64 and x86_64 server binaries. They never call the upstream `deploy.sh`.

- Binary: `/usr/local/bin/csqtt-lalune`
- Unit: `csqtt-lalune.service`
- Config: `/etc/csqtt-lalune`
- State/logs: `/var/lib/csqtt-lalune`, `/var/log/csqtt-lalune`
- UDP peer port: `47000`; web TCP port: `47002`
- TUN/subnet and policy identifiers are compiled into the isolated binary: `csqtt-lalune0`, `10.67.68.0/24`, policy tables `47001` and `47066`.

The installer fails closed on unexpected pre-existing paths/units and occupied ports; it never kills listeners or edits global sysctl, main/default routes, or generic CSQTT files. It requires root, Linux (ARM64 or x86_64) and systemd. The DeployManager passes a short-lived secrets file; the installer validates it and writes `/etc/csqtt-lalune/server.env` with mode `0600`. The generated unit reads this protected file and uses the requested UDP/TCP ports (defaults `47000`/`47002`). The uninstaller removes only the unit, binary and marked LaLune library directory. Config/state/logs remain unless `--purge` is explicitly supplied.

**Production deployment remains gated.** The Deploy button is wired to the isolated installer, but CI must pass the actual API-to-SSH install/uninstall E2E and server startup checks in a disposable environment with pre-existing CSQTT services before deploying to NanoPi. The script intentionally does not create global firewall rules or call upstream cleanup routines.
