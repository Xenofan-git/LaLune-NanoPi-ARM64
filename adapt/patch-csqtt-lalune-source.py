#!/usr/bin/env python3
"""Patch pinned upstream CSQTT v2.1.9 source for an isolated LaLune dataplane."""
from pathlib import Path

root = Path("server-source/rust-server")
paths = {
    "net": root / "net_setup.rs",
    "tun": root / "tun_device.rs",
}
sources = {key: path.read_text() for key, path in paths.items()}
replacements = [
    ("net", 'pub const TUN_IFACE: &str = "csqtt1";', 'pub const TUN_IFACE: &str = "csqtt-lalune0";', "net_setup TUN interface"),
    ("net", 'pub const TUN_ADDR: &str = "10.66.67.1";', 'pub const TUN_ADDR: &str = "10.67.68.1";', "net_setup TUN address"),
    ("tun", 'pub const TUN_IFACE: &str = "csqtt1";', 'pub const TUN_IFACE: &str = "csqtt-lalune0";', "tun_device TUN interface"),
    ("tun", 'pub const TUN_SUBNET: &str = "10.66.67.0/24";', 'pub const TUN_SUBNET: &str = "10.67.68.0/24";', "TUN subnet"),
    ("tun", 'const SUBNET_PREFIX: [u8; 3] = [10, 66, 67];', 'const SUBNET_PREFIX: [u8; 3] = [10, 67, 68];', "route prefix"),
    ("tun", '[10, 66, 67, last]', '[10, 67, 68, last]', "test subnet helper"),
    ("tun", '[10, 66, 68, 2]', '[10, 67, 69, 2]', "foreign subnet test"),
]
for key, old, new, label in replacements:
    if sources[key].count(old) != 1:
        raise SystemExit(f"{label}: expected exactly one source occurrence, found {sources[key].count(old)}")
    sources[key] = sources[key].replace(old, new, 1)

for key, path in paths.items():
    path.write_text(sources[key])

for path in root.glob("*.rs"):
    text = path.read_text()
    if "csqtt1" in text or "10.66.67" in text:
        raise SystemExit(f"unpatched shared interface/subnet reference remains in {path}")
if 'pub const TUN_IFACE: &str = "csqtt-lalune0";' not in sources["net"]:
    raise SystemExit("dedicated interface missing from net_setup.rs")
if 'pub const TUN_IFACE: &str = "csqtt-lalune0";' not in sources["tun"]:
    raise SystemExit("dedicated interface missing from tun_device.rs")
if 'pub const TUN_SUBNET: &str = "10.67.68.0/24";' not in sources["tun"]:
    raise SystemExit("dedicated subnet missing")
print("Patched CSQTT v2.1.9: TUN=csqtt-lalune0, subnet=10.67.68.0/24")
