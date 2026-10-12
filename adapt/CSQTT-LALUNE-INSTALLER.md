# CSQTT-LaLune installer contract

These scripts install only the separately patched CSQTT v2.1.9 ARM64 dataplane. They never call the upstream `deploy.sh`.

- Binary: `/usr/local/bin/csqtt-lalune`
- Unit: `csqtt-lalune.service`
- Config: `/etc/csqtt-lalune`
- State/logs: `/var/lib/csqtt-lalune`, `/var/log/csqtt-lalune`
- UDP peer port: `47000`; web TCP port: `47002`
- TUN/subnet and policy identifiers are compiled into the isolated binary: `csqtt-lalune0`, `10.67.68.0/24`, policy tables `47001` and `47066`.

The installer fails closed on unexpected pre-existing paths/units and occupied ports; it never kills listeners or edits global sysctl, main/default routes, or generic CSQTT files. It requires root, ARM64 Linux and systemd. The uninstaller removes only the unit, binary and marked LaLune library directory. Config/state/logs remain unless `--purge` is explicitly supplied.

**This is not yet authorized for production deployment.** Before using it on NanoPi, CI must validate the script, the packaged asset must include the scripts, and the generated service must be tested against the actual CSQTT runtime's startup/config behavior in a disposable environment with pre-existing CSQTT services. The script intentionally does not create global firewall rules or call upstream cleanup routines.
