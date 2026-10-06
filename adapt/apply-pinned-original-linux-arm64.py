from pathlib import Path

UPSTREAM = Path("upstream-lalune")
PROTO = UPSTREAM / "Desktop/Libs/protocols.go"
LINUX = UPSTREAM / "Desktop/Linux/app_linux.go"

def replace_once(path, old, new):
    s = path.read_text()
    if old not in s:
        raise SystemExit(f"marker not found in {path}: {old!r}")
    path.write_text(s.replace(old, new, 1))

replace_once(
    PROTO,
    '''\t\tdefault:\n\t\t\treturn "client-linux-x86_64"''',
    '''\t\tdefault:\n\t\t\tif goarch == "arm64" {\n\t\t\t\treturn "client-linux-arm64"\n\t\t\t}\n\t\t\treturn "client-linux-x86_64"'''
)

s = LINUX.read_text()
start = s.index("func (t *LinuxTun) SetupRoutes")
end = s.index("\n}\n\nfunc (t *LinuxTun) CleanupRoutes", start) + 2
setup = '''func (t *LinuxTun) SetupRoutes(tunIP, tunDNS string) {
\tt.mu.Lock()
\tdefer t.mu.Unlock()
\tt.app.core.AddLog(fmt.Sprintf("[TUN] Настройка TUN (IP: %s, DNS: %s)...", tunIP, tunDNS))

\tcmd := fmt.Sprintf("ip tuntap add dev csqtt0 mode tun && ip addr add %s/32 dev csqtt0 && ip link set csqtt0 up && ip link set csqtt0 mtu 1300", tunIP)
\tt.app.runSudo(cmd)

\tfor _, dns := range strings.Split(tunDNS, ",") {
\t\tdns = strings.TrimSpace(dns)
\t\tif dns != "" {
\t\t\tt.app.runSudo(fmt.Sprintf("echo 'nameserver %s' >> /etc/resolv.conf", dns))
\t\t}
\t}

\tt.app.runSudo("ip rule del pref 22020 2>/dev/null || true")
\tt.app.runSudo("ip route flush table 202 2>/dev/null || true")
\tt.app.runSudo("ip route replace 192.168.4.0/24 dev eth0 table 202")
\tt.app.runSudo("ip route replace 192.168.5.0/24 dev eth1 table 202")
\tt.app.runSudo("ip route replace default dev csqtt0 table 202")
\tt.app.runSudo("ip rule add pref 22020 from 192.168.5.0/24 lookup 202")

\tt.app.core.AddLog("[TUN] TUN настроен успешно (policy table 202)")
}'''
s = s[:start] + setup + s[end:]
start = s.index("func (t *LinuxTun) CleanupRoutes")
end = s.index("\n}\n\nfunc (t *LinuxTun) AddBypassRoute", start) + 2
cleanup = '''func (t *LinuxTun) CleanupRoutes() {
\tt.mu.Lock()
\tdefer t.mu.Unlock()
\tt.app.core.AddLog("[TUN] Удаление TUN...")
\tt.app.runSudo("ip rule del pref 22020 2>/dev/null || true")
\tt.app.runSudo("ip route flush table 202 2>/dev/null || true")
\tt.app.runSudo("ip tuntap del dev csqtt0 mode tun 2>/dev/null || true")
\tt.app.core.AddLog("[TUN] TUN удалён")
}'''
s = s[:start] + cleanup + s[end:]
LINUX.write_text(s)
print("Pinned original LaLune NanoPi adaptation applied")
