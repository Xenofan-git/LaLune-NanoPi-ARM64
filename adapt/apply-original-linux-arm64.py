from pathlib import Path

ROOT = Path("upstream-lalune/Backend/Desktop/src")

core = ROOT / "core_manager.rs"
s = core.read_text()
marker = '"client-linux-x86_64"'
if marker not in s:
    raise SystemExit("core asset marker not found")
core.write_text(s.replace(marker, '"client-linux-arm64"', 1))

vpn = ROOT / "vpn.rs"
s = vpn.read_text()

dns_marker = 'pub const DEFAULT_DNS: &str = "8.8.8.8,8.8.4.4";'
constants = '''pub const POLICY_TABLE: u32 = 202;
pub const POLICY_PREF: u32 = 22020;
pub const CLIENT_SUBNET: &str = "192.168.5.0/24";'''
if dns_marker not in s:
    raise SystemExit("vpn constants marker not found")
s = s.replace(dns_marker, dns_marker + "\n" + constants, 1)

route_old = '''    run_sudo(
        &format!("ip route add default dev {}", TUN_NAME),
        events,
    );'''
route_new = '''    // Keep NanoPi main routing untouched; route only eth1 clients via LaLune.
    run_sudo(
        &format!("ip rule del pref {} 2>/dev/null || true", POLICY_PREF),
        events,
    );
    run_sudo(
        &format!("ip route flush table {} 2>/dev/null || true", POLICY_TABLE),
        events,
    );
    run_sudo(
        &format!("ip route replace 192.168.4.0/24 dev eth0 table {}", POLICY_TABLE),
        events,
    );
    run_sudo(
        &format!("ip route replace {} dev eth1 table {}", CLIENT_SUBNET, POLICY_TABLE),
        events,
    );
    run_sudo(
        &format!("ip route replace default dev {} table {}", TUN_NAME, POLICY_TABLE),
        events,
    );
    run_sudo(
        &format!("ip rule add pref {} from {} lookup {}", POLICY_PREF, CLIENT_SUBNET, POLICY_TABLE),
        events,
    );'''
if route_old not in s:
    raise SystemExit("Linux route block not found")
s = s.replace(route_old, route_new, 1)

cleanup_old = '''    run_sudo(
        &format!("ip route del default dev {} 2>/dev/null || true", TUN_NAME),
        events,
    );'''
cleanup_new = '''    run_sudo(
        &format!(
            "ip rule del pref {} 2>/dev/null || true; ip route flush table {} 2>/dev/null || true",
            POLICY_PREF, POLICY_TABLE
        ),
        events,
    );'''
if cleanup_old not in s:
    raise SystemExit("Linux cleanup block not found")

vpn.write_text(s.replace(cleanup_old, cleanup_new, 1))
print("NanoPi LaLune patch applied: table=202 pref=22020 subnet=192.168.5.0/24")
