#!/usr/bin/env python3
"""Patch pinned upstream CSQTT v2.1.9 source for an isolated LaLune dataplane."""
from pathlib import Path

root = Path("server-source/rust-server")
paths = {
    "net": root / "net_setup.rs",
    "tun": root / "tun_device.rs",
    "proxy": root / "proxy_route.rs",
    "model": root / "model.rs",
    "protocol": root / "protocol.rs",
}
sources = {key: path.read_text() for key, path in paths.items()}
replacements = [
    ("net", 'pub const TUN_IFACE: &str = "csqtt1";', 'pub const TUN_IFACE: &str = "csqtt-lalune0";', "net_setup TUN interface", 1),
    ("net", 'pub const TUN_ADDR: &str = "10.66.67.1";', 'pub const TUN_ADDR: &str = "10.67.68.1";', "net_setup TUN address", 1),
    ("tun", 'pub const TUN_IFACE: &str = "csqtt1";', 'pub const TUN_IFACE: &str = "csqtt-lalune0";', "tun_device TUN interface", 1),
    ("tun", 'pub const TUN_SUBNET: &str = "10.66.67.0/24";', 'pub const TUN_SUBNET: &str = "10.67.68.0/24";', "TUN subnet", 1),
    ("tun", 'const SUBNET_PREFIX: [u8; 3] = [10, 66, 67];', 'const SUBNET_PREFIX: [u8; 3] = [10, 67, 68];', "route prefix", 1),
    ("tun", '[10, 66, 67, last]', '[10, 67, 68, last]', "subnet helper", 1),
    # Upstream uses this foreign-subnet test address twice; both occurrences must move
    # together so runtime logic and its unit test agree with the new LaLune subnet.
    ("tun", '[10, 66, 68, 2]', '[10, 67, 69, 2]', "foreign subnet reference", 2),
    # Protocol fixtures embed the allocated client subnet in expected payloads.
    ("protocol", "10.66.67", "10.67.68", "protocol client subnet", 2),
]
for key, old, new, label, expected_count in replacements:
    count = sources[key].count(old)
    if count != expected_count:
        raise SystemExit(f"{label}: expected {expected_count} source occurrence(s), found {count}")
    sources[key] = sources[key].replace(old, new)

# Device address allocation and legacy-import fixtures also embed the upstream subnet.
# Move every occurrence in model.rs so newly allocated client IPs use the LaLune subnet.
model_count = sources["model"].count("10.66.67")
if model_count < 1:
    raise SystemExit("model.rs: expected legacy client subnet references to rename")
sources["model"] = sources["model"].replace("10.66.67", "10.67.68")

# The proxy-route module also writes rp_filter against the TUN name and
# mutates policy routing / iptables. Give every policy table, mark, and rule
# comment its own namespace; otherwise its startup/cleanup can delete another
# CSQTT instance's rules or flush a shared routing table.
proxy_count = sources["proxy"].count("csqtt1")
if proxy_count < 1:
    raise SystemExit("proxy_route.rs: expected legacy TUN references to rename")
sources["proxy"] = sources["proxy"].replace("csqtt1", "csqtt-lalune0")

proxy_policy_replacements = [
    ('const LEGACY_POLICY_TABLE: &str = "1066";', 'const LEGACY_POLICY_TABLE: &str = "47066";', "legacy policy table"),
    ('const LEGACY_POLICY_PRIORITY: &str = "1066";', 'const LEGACY_POLICY_PRIORITY: &str = "47066";', "legacy policy priority"),
    ('const NAT_COMMENT: &str = "CSQTT_LOCAL_SOCKS";', 'const NAT_COMMENT: &str = "CSQTT_LALUNE_LOCAL_SOCKS";', "local SOCKS NAT marker"),
    ('const MARK_COMMENT: &str = "CSQTT_LOCAL_SOCKS_MARK";', 'const MARK_COMMENT: &str = "CSQTT_LALUNE_LOCAL_SOCKS_MARK";', "local SOCKS mark marker"),
    ('const POLICY_MARK: &str = "0x422";', 'const POLICY_MARK: &str = "0x6742";', "local SOCKS policy mark"),
    ('const LEGACY_NAT_COMMENT: &str = "CSQTT_SOCKS";', 'const LEGACY_NAT_COMMENT: &str = "CSQTT_LALUNE_SOCKS";', "legacy NAT marker"),
    ('const LEGACY_QUIC_COMMENT: &str = "CSQTT_CASCADE_NO_QUIC";', 'const LEGACY_QUIC_COMMENT: &str = "CSQTT_LALUNE_CASCADE_NO_QUIC";', "legacy QUIC marker"),
    ('const TPROXY_TABLE: &str = "30001";', 'const TPROXY_TABLE: &str = "47001";', "TPROXY table"),
    ('const TPROXY_PRIORITY: &str = "30001";', 'const TPROXY_PRIORITY: &str = "47001";', "TPROXY priority"),
    ('const TPROXY_RULE_MARK: &str = "0x7531/0x7531";', 'const TPROXY_RULE_MARK: &str = "0x6741/0x6741";', "TPROXY mark"),
]
for old, new, label in proxy_policy_replacements:
    count = sources["proxy"].count(old)
    if count != 1:
        raise SystemExit(f"proxy_route.rs {label}: expected one declaration, found {count}")
    sources["proxy"] = sources["proxy"].replace(old, new, 1)

# Rule cleanup is marker-based, so the TPROXY comment must be unique as well.
sources["proxy"] = sources["proxy"].replace("CSQTT_TPROXY", "CSQTT_LALUNE_TPROXY")

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
if '[10, 67, 69, 2]' not in sources["tun"]:
    raise SystemExit("foreign subnet test reference missing after patch")
for marker in [
    'const LEGACY_POLICY_TABLE: &str = "47066";',
    'const TPROXY_TABLE: &str = "47001";',
    'const TPROXY_RULE_MARK: &str = "0x6741/0x6741";',
    'const NAT_COMMENT: &str = "CSQTT_LALUNE_LOCAL_SOCKS";',
    'CSQTT_LALUNE_TPROXY',
]:
    if marker not in sources["proxy"]:
        raise SystemExit(f"dedicated proxy routing namespace missing: {marker}")
for forbidden in ['"1066"', '"30001"', '"0x422"', '"0x7531/0x7531"', 'CSQTT_TPROXY', 'CSQTT_LOCAL_SOCKS', 'CSQTT_SOCKS']:
    if forbidden in sources["proxy"]:
        raise SystemExit(f"shared proxy-routing marker remains: {forbidden}")
print("Patched CSQTT v2.1.9: TUN=csqtt-lalune0, subnet=10.67.68.0/24, isolated proxy policy namespace")
