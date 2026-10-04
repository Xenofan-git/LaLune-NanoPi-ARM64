# Original LaLune — NanoPi ARM64 adaptation

This branch is based on the original Linux backend from Endlad2/LaLune.

Adaptations:
- Linux CSQTT core asset: client-linux-arm64.
- Linux routing no longer changes the main routing table.
- LaLune uses policy routing table 200.
- Traffic sourced from 192.168.5.0/24 is routed through csqtt0.
- Main NanoPi routing (including the physical default route via eth0) remains untouched.
- On disconnect, only the LaLune rule/table are removed.

The adaptation is intentionally kept separate from the existing lalune-gateway fallback.

Upstream:
https://github.com/Endlad2/LaLune
