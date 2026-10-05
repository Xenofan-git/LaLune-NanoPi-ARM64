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

setup_start = s.find('#[cfg(target_os = "linux")]\nfn setup_routes_linux(')
cleanup_start = s.find('#[cfg(target_os = "linux")]\nfn cleanup_routes_linux(')
run_sudo_start = s.find('#[cfg(target_os = "linux")]\nfn run_sudo(')
if min(setup_start, cleanup_start, run_sudo_start) < 0 or not (setup_start < cleanup_start < run_sudo_start):
    raise SystemExit("Linux route function boundaries not found")

setup_fn = '''#[cfg(target_os = "linux")]
fn setup_routes_linux(tun_ip: &str, tun_dns: &str, events: &EventBus) {
    for dns in tun_dns.split(',') {
        let dns = dns.trim();
        if dns.is_empty() {
            continue;
        }
        run_sudo(&format!("echo 'nameserver {}' >> /etc/resolv.conf", dns), events);
    }

    // Keep NanoPi main routing untouched; route only eth1 clients via LaLune.
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
        &format!("ip route replace default dev {} table {}", "csqtt0", POLICY_TABLE),
        events,
    );
    run_sudo(
        &format!("ip rule add pref {} from {} lookup {}", POLICY_PREF, CLIENT_SUBNET, POLICY_TABLE),
        events,
    );

    let _ = tun_ip;
}

'''
s = s[:setup_start] + setup_fn + s[cleanup_start:]

cleanup_fn = '''#[cfg(target_os = "linux")]
fn cleanup_routes_linux(events: &EventBus) {
    run_sudo(
        &format!(
            "ip rule del pref {} 2>/dev/null || true; ip route flush table {} 2>/dev/null || true",
            POLICY_PREF, POLICY_TABLE
        ),
        events,
    );
}

'''
cleanup_start = s.find('#[cfg(target_os = "linux")]\nfn cleanup_routes_linux(')
run_sudo_start = s.find('#[cfg(target_os = "linux")]\nfn run_sudo(')
if cleanup_start < 0 or run_sudo_start < 0 or cleanup_start >= run_sudo_start:
    raise SystemExit("Linux cleanup boundaries not found")
s = s[:cleanup_start] + cleanup_fn + s[run_sudo_start:]

vpn.write_text(s)
print("NanoPi LaLune patch applied: table=202 pref=22020 subnet=192.168.5.0/24")
