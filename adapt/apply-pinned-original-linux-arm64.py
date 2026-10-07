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

# NanoPi dataplane adaptation: the pinned original leaves LinuxTun.Start empty.
# Keep the original UDP core protocol, but bridge Linux TUN packets to that UDP
# socket using /dev/net/tun. This is intentionally the only dataplane deviation.
s=s.replace(
'''type LinuxTun struct {
\tapp          *App
\tbypassRoutes []string
\tmu           sync.Mutex
}''',
'''type LinuxTun struct {
\tapp          *App
\tbypassRoutes []string
\tmu           sync.Mutex
\ttunFile      *os.File
}''', 1)

s=s.replace(
'''import "lalune-desktop/Libs"''',
'''import "lalune-desktop/Libs"

import "golang.org/x/sys/unix"''', 1)

old='''func (t *LinuxTun) Setup() error              { return nil }
func (t *LinuxTun) Start(_ net.Conn, _ *bool) {}
func (t *LinuxTun) Stop()                     {}'''
new='''func (t *LinuxTun) Setup() error { return nil }

func (t *LinuxTun) Start(udpConn net.Conn, running *bool) {
\tt.mu.Lock()
\tif t.tunFile != nil {
\t\tt.mu.Unlock()
\t\treturn
\t}

\tf, err := os.OpenFile("/dev/net/tun", os.O_RDWR, 0)
\tif err != nil {
\t\tt.mu.Unlock()
\t\tt.app.core.AddLog(fmt.Sprintf("[TUN] Не удалось открыть /dev/net/tun: %v", err))
\t\treturn
\t}

\tifr, err := unix.NewIfreq("csqtt0")
\tif err != nil {
\t\tf.Close()
\t\tt.mu.Unlock()
\t\tt.app.core.AddLog(fmt.Sprintf("[TUN] Не удалось создать ifreq: %v", err))
\t\treturn
\t}
\tifr.SetUint16(unix.IFF_TUN | unix.IFF_NO_PI)
\tif err := unix.IoctlIfreq(int(f.Fd()), unix.TUNSETIFF, ifr); err != nil {
\t\tf.Close()
\t\tt.mu.Unlock()
\t\tt.app.core.AddLog(fmt.Sprintf("[TUN] TUNSETIFF csqtt0: %v", err))
\t\treturn
\t}

\tt.tunFile = f
\tt.mu.Unlock()
\tt.app.core.AddLog("[TUN] Linux TUN↔UDP bridge запущен")

\tgo func() {
\t\tbuf := make([]byte, 65535)
\t\tfor *running {
\t\t\tn, err := f.Read(buf)
\t\t\tif err != nil {
\t\t\t\treturn
\t\t\t}
\t\t\tif n > 0 {
\t\t\t\tif _, err := udpConn.Write(buf[:n]); err != nil {
\t\t\t\t\treturn
\t\t\t\t}
\t\t\t}
\t\t}
\t}()

\tgo func() {
\t\tbuf := make([]byte, 65535)
\t\tfor *running {
\t\t\tn, err := udpConn.Read(buf)
\t\t\tif err != nil {
\t\t\t\treturn
\t\t\t}
\t\t\tif n > 0 {
\t\t\t\tif _, err := f.Write(buf[:n]); err != nil {
\t\t\t\t\treturn
\t\t\t\t}
\t\t\t}
\t\t}
\t}()
}

func (t *LinuxTun) Stop() {
\tt.mu.Lock()
\tf := t.tunFile
\tt.tunFile = nil
\tt.mu.Unlock()
\tif f != nil {
\t\t_ = f.Close()
\t}
}'''
if old not in s:
    raise SystemExit("LinuxTun Start/Stop marker not found")
s=s.replace(old,new,1)

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
