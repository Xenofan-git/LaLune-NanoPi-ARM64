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

# The pinned Go wrapper invokes DeployManager with --port, but the original
# DeployManager CLI calls this option --ssh-port. Keep the original UI/API
# contract while fixing the actual CLI invocation.
BRIDGE = UPSTREAM / "Desktop/Libs/bridge.go"

# New CSQTT core Auto VK protocol: stdin bootstrap replaces obsolete --token.
bs = BRIDGE.read_text()
bs = bs.replace('import (\n\t"fmt"', 'import (\n\t"encoding/base64"\n\t"encoding/json"\n\t"fmt"', 1)
old = '\tif isAutoVk {\n\t\ttoken := b.Core.ReadTokenFromFile()\n\t\tif token == "" {\n\t\t\tb.Core.AddLog("[АВТО ВК] ПРЕДУПРЕЖДЕНИЕ: token.json не найден или пуст — ядро упадёт")\n\t\t} else {\n\t\t\tcmd = append(cmd, "--token", token)\n\t\t\tb.Core.AddLog("[АВТО ВК] Токен передан из token.json")\n\t\t}\n\t}\n'
new = '\tif isAutoVk {\n\t\ttoken := b.Core.ReadTokenFromFile()\n\t\tif token == "" {\n\t\t\tb.Core.AddLog("[АВТО ВК] ПРЕДУПРЕЖДЕНИЕ: token.json не найден или пуст — ядро не запустит Auto JS")\n\t\t} else {\n\t\t\tb.Core.AddLog("[АВТО ВК] VK bootstrap подготовлен для stdin")\n\t\t}\n\t}\n'
if old not in bs: raise SystemExit("bridge auto-vk marker not found")
bs = bs.replace(old, new, 1)
anchor = 'func (b *Bridge) ParseTunconf(line string) (string, string) {'
method = 'func (b *Bridge) AutoVkBootstrap() string {\n\tsettings := b.Core.GetSettings()\n\tif settings.AuthMode != "autoVk" { return "" }\n\ttoken := b.Core.ReadTokenFromFile()\n\tif token == "" { return "" }\n\tpayload, err := json.Marshal(map[string]string{"token": token})\n\tif err != nil { return "" }\n\treturn "VK_JS_BOOTSTRAP:" + base64.StdEncoding.EncodeToString(payload) + "\\n"\n}\n\n'
if anchor not in bs: raise SystemExit("bridge anchor not found")
bs = bs.replace(anchor, method + anchor, 1)
BRIDGE.write_text(bs)
DEPLOY_GO = UPSTREAM / "Desktop/Libs/deploy.go"
s = DEPLOY_GO.read_text()
old = '"--port", itoa(req.SSHPort)'
new = '"--ssh-port", itoa(req.SSHPort)'
if old not in s:
    raise SystemExit(f"marker not found in {DEPLOY_GO}: {old!r}")
DEPLOY_GO.write_text(s.replace(old, new, 1))

# Linux runner must feed the new Auto JS bootstrap to core stdin.
s = LINUX.read_text()
old = '\tcmd := exec.Command("sh", "-c", r.app.runSudoCommand(cmdLine))\n\tcmd.Stdin = os.Stdin\n\tcmd.Stdout = os.Stdout\n\tcmd.Stderr = os.Stderr\n'
new = '\tcmd := exec.Command("sh", "-c", r.app.runSudoCommand(cmdLine))\n\tstdin, err := cmd.StdinPipe()\n\tif err != nil {\n\t\tbridge.Core.AddLog(fmt.Sprintf("[ERROR] Не удалось подготовить stdin ядра: %v", err))\n\t\tbridge.Core.SetConnected(false)\n\t\treturn\n\t}\n\tcmd.Stdout = os.Stdout\n\tcmd.Stderr = os.Stderr\n'
if old not in s: raise SystemExit("stdin marker not found")
s = s.replace(old, new, 1)
old = '\tif err := cmd.Start(); err != nil {\n\t\tbridge.Core.AddLog(fmt.Sprintf("[ERROR] Не удалось запустить: %v", err))\n\t\tbridge.Core.SetConnected(false)\n\t\treturn\n\t}\n'
new = '\tif err := cmd.Start(); err != nil {\n\t\t_ = stdin.Close()\n\t\tbridge.Core.AddLog(fmt.Sprintf("[ERROR] Не удалось запустить: %v", err))\n\t\tbridge.Core.SetConnected(false)\n\t\treturn\n\t}\n\tif bootstrap := bridge.AutoVkBootstrap(); bootstrap != "" {\n\t\tif _, err := io.WriteString(stdin, bootstrap); err != nil {\n\t\t\tbridge.Core.AddLog(fmt.Sprintf("[АВТО ВК] Ошибка передачи bootstrap: %v", err))\n\t\t} else {\n\t\t\tbridge.Core.AddLog("[АВТО ВК] VK_JS_BOOTSTRAP передан в core")\n\t\t}\n\t}\n\t_ = stdin.Close()\n'
if old not in s: raise SystemExit("start marker not found")
s = s.replace(old, new, 1)
s = s.replace('\t"time"\n)', '\t"time"\n\t"io"\n)', 1)
LINUX.write_text(s)

# Keep the core stdin pipe alive for asynchronous CAPTCHA_RESULT responses.
s = LINUX.read_text()
s = s.replace("type LinuxRunner struct {", "var linuxRunnerInputs sync.Map\n\ntype LinuxRunner struct {", 1)
s = s.replace("\tlinuxRunnerInputs.Store(r, stdin)\n\tif bootstrap := bridge.AutoVkBootstrap(); bootstrap != \"\" {", "\tlinuxRunnerInputs.Store(r, stdin)\n\tif bootstrap := bridge.AutoVkBootstrap(); bootstrap != \"\" {", 1)
s = s.replace("\\tcmd.Wait()", "\tcmd.Wait()\n\tif v, ok := linuxRunnerInputs.LoadAndDelete(r); ok { _ = v.(io.WriteCloser).Close() }", 1)
method = '''func (r *LinuxRunner) SubmitCaptchaResult(result string) bool {
\tif len(result) == 0 || len(result) > 16384 || strings.ContainsAny(result, "\\r\\n") { return false }
\tv, ok := linuxRunnerInputs.Load(r)
\tif !ok { return false }
\t_, err := io.WriteString(v.(io.WriteCloser), "CAPTCHA_RESULT|"+result+"\\n")
\treturn err == nil
}
'''
s = s.replace("func NewApp() *App {", method + "\nfunc NewApp() *App {", 1)
LINUX.write_text(s)

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

# Start the original Bridge TUN↔UDP packet bridge after Linux route setup.
s = LINUX.read_text()
# Prevent concurrent core workers sharing one Bridge/TUN state on NanoPi.
old_runner_guard = """func (r *LinuxRunner) StartCore(cmdArgs []string, listenPort int, bridge *libs.Bridge) {
	r.startCoreWithSudo(cmdArgs, listenPort, bridge)
}"""
new_runner_guard = old_runner_guard
if old_runner_guard not in s:
    raise SystemExit("LinuxRunner.StartCore marker not found")
s = s.replace(old_runner_guard, new_runner_guard, 1)

old_runner = """		if tun, ok := bridge.Tun.(*LinuxTun); ok {
			tun.SetupRoutes(tunIP, tunDNS)
		}"""
new_runner = """        if tun, ok := bridge.Tun.(*LinuxTun); ok {
            tun.SetupRoutes(tunIP, tunDNS)
            bridge.StartTunnel(coreListenPort)
        }"""
if old_runner not in s:
    raise SystemExit("LinuxRunner TUN setup marker not found")
s = s.replace(old_runner, new_runner, 1)

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

# NanoPi headless panel: use installed DeployManager and bundled CSQTT assets.
s = DEPLOY_GO.read_text()
old = 'if wd, err := os.Getwd(); err == nil {'
new = 'if st, err := os.Stat("/usr/local/lib/lalune/deploy-manager"); err == nil && !st.IsDir() {\n\t\treturn "/usr/local/lib/lalune/deploy-manager"\n\t}\n\tif wd, err := os.Getwd(); err == nil {'
if old not in s: raise SystemExit("deploy manager path marker missing")
s = s.replace(old, new, 1)
old = '\tif req.ManualPorts {'
new = '\tif strings.EqualFold(strings.TrimSpace(req.Protocol), "CSQTT") {\n\t\tif st, err := os.Stat("/usr/local/lib/lalune/server-assets"); err == nil && st.IsDir() {\n\t\t\targs = append(args, "--local-binary-dir", "/usr/local/lib/lalune/server-assets")\n\t\t}\n\t}\n\tif req.ManualPorts {'
if old not in s: raise SystemExit("manual ports marker missing")
DEPLOY_GO.write_text(s.replace(old, new, 1))

# NanoPi build version: keep the original InfoPage wording but report this adapted build.
INFO = UPSTREAM / "Frontend/Core/lib/pages/info_page.dart"
replace_once(INFO, "static const String _laluneVersion = '0.5.0';", "static const String _laluneVersion = '0.6.0';")

# Restore the original Deploy tab and connect the Flutter Web UI to NanoPi HTTP API.
MAIN = UPSTREAM / "Frontend/Core/lib/main.dart"
NAV = UPSTREAM / "Frontend/Core/lib/widgets/navbar.dart"
INDEX = UPSTREAM / "Frontend/Core/web/index.html"
API_JS = UPSTREAM / "Frontend/Core/web/api.js"
NANOPI_JS = Path(__file__).with_name("nanopi.js")
replace_once(MAIN, "import 'pages/logs_page.dart';", "import 'pages/logs_page.dart';\nimport 'pages/deploy_page.dart';")
replace_once(MAIN, """      case 3:\n        return const LogsPage();\n      // case 4 (Деплой) убран из UI — вкладка отключена, страница сохранена.\n      default:""", """      case 3:\n        return const LogsPage();\n      case 4:\n        return const DeployPage();\n      default:""")
replace_once(NAV, """    _NavItem(icon: 'assets/logs.png', label: 'Логи'),\n    // Вкладка \"Деплой\" временно убрана из UI (логика в deploy_page.dart сохранена).""", """    _NavItem(icon: 'assets/logs.png', label: 'Логи'),\n    _NavItem(icon: 'assets/info.png', label: 'Деплой'),""")
replace_once(INDEX, "    {{flutter_bootstrap_js}}", "    <script src=\"api.js\"></script>\n    {{flutter_bootstrap_js}}")
API_JS.write_text(NANOPI_JS.read_text())

# ============================================================
# Direct routing: destination domains/IPs bypass CSQTT.
# Only traffic sourced from the LaLune client subnet is affected.
# ============================================================

COMMON = UPSTREAM / "Desktop/Libs/common.go"
LINUX = UPSTREAM / "Desktop/Linux/app_linux.go"
API_DART = UPSTREAM / "Frontend/Core/lib/api.dart"
SETTINGS_PAGE = UPSTREAM / "Frontend/Core/lib/pages/settings_page.dart"

replace_once(
    COMMON,
    '''\tValidateVkHashes        bool   `json:"validateVkHashes"`\n\n\t// Экспериментальные функции.''',
    '''\tValidateVkHashes        bool   `json:"validateVkHashes"`\n\tDirectDomains           string `json:"directDomains"`\n\tDirectIPs               string `json:"directIPs"`\n\n\t// Экспериментальные функции.''',
)

linux_direct = r'''
const directMark = "0x4c4c"
const directRulePref = "22010"
const directNftPath = "/run/lalune-direct.nft"
const directDnsmasqPath = "/etc/dnsmasq.d/lalune-direct.conf"

func splitDirectList(raw string) []string {
\treturn strings.FieldsFunc(raw, func(r rune) bool {
\t\treturn r == ',' || r == ';' || r == '\\n' || r == '\\r' || r == '\\t' || r == ' '
\t})
}

func validDirectDomain(s string) bool {
\tif s == "" || strings.ContainsAny(s, "/#:=<>\\"'\\\\") {
\t\treturn false
\t}
\treturn regexp.MustCompile("(?i)^([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\\.)+[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$").MatchString(s)
}
func normalizeDirectIPs(raw string) ([]string, error) {
\tvar out []string
\tfor _, token := range splitDirectList(raw) {
\t\tif token == "" {
\t\t\tcontinue
\t\t}
\t\tif ip := net.ParseIP(token); ip != nil {
\t\t\tif ip.To4() == nil {
\t\t\t\treturn nil, fmt.Errorf("IPv6 пока не поддерживается: %s", token)
\t\t\t}
\t\t\tout = append(out, ip.To4().String())
\t\t\tcontinue
\t\t}
\t\t_, n, err := net.ParseCIDR(token)
\t\tif err != nil || n.IP.To4() == nil {
\t\t\treturn nil, fmt.Errorf("некорректный IPv4/CIDR: %s", token)
\t\t}
\t\tout = append(out, n.String())
\t}
\treturn out, nil
}

func (t *LinuxTun) cleanupDirectRoutingLocked() {
\tt.app.runSudo("ip rule del pref " + directRulePref + " 2>/dev/null || true")
\tt.app.runSudo("nft delete table inet lalune_direct 2>/dev/null || true")
\tif _, err := os.Stat(directDnsmasqPath); err == nil {
\t\t_ = os.Remove(directDnsmasqPath)
\t\t_ = t.app.runSudo("systemctl restart dnsmasq")
\t}
\t_ = os.Remove(directNftPath)
}

func (t *LinuxTun) applyDirectRoutingLocked() error {
\tsettings := t.app.core.GetSettings()
\tdomains := splitDirectList(settings.DirectDomains)
\tips, err := normalizeDirectIPs(settings.DirectIPs)
\tif err != nil {
\t\treturn err
\t}

\tfor _, d := range domains {
\t\tif !validDirectDomain(d) {
\t\t\treturn fmt.Errorf("некорректный домен Direct: %s", d)
\t\t}
\t}

\tt.app.runSudo("ip rule del pref " + directRulePref + " 2>/dev/null || true")
\tt.app.runSudo("nft delete table inet lalune_direct 2>/dev/null || true")
\thadDnsmasq := false
\tif _, err := os.Stat(directDnsmasqPath); err == nil {
\t\thadDnsmasq = true
\t\t_ = os.Remove(directDnsmasqPath)
\t}
\t_ = os.Remove(directNftPath)

\tif len(domains) == 0 && len(ips) == 0 {
\t\tif hadDnsmasq {
\t\t\t_ = t.app.runSudo("systemctl restart dnsmasq")
\t\t}
\t\treturn nil
\t}

\tvar nft strings.Builder
\tnft.WriteString("table inet lalune_direct {\n")
\tnft.WriteString("  set direct4 { type ipv4_addr; flags interval;")
\tif len(ips) > 0 {
\t\tnft.WriteString(" elements = { ")
\t\tnft.WriteString(strings.Join(ips, ", "))
\t\tnft.WriteString(" }")
\t}
\tnft.WriteString(" }\n")
\tnft.WriteString("  chain prerouting { type filter hook prerouting priority -150; policy accept;\n")
\tnft.WriteString("    ip saddr 192.168.5.0/24 ip daddr @direct4 meta mark set " + directMark + "\n")
\tnft.WriteString("  }\n")
\tnft.WriteString("}\n")

\tif err := os.WriteFile(directNftPath, []byte(nft.String()), 0600); err != nil {
\t\treturn fmt.Errorf("запись nft-конфига: %w", err)
\t}
\tif err := t.app.runSudo("nft -f " + directNftPath); err != nil {
\t\treturn fmt.Errorf("nft direct policy: %w", err)
\t}

\tif len(domains) > 0 {
\t\tline := "nftset=/"
\t\tfor i, d := range domains {
\t\t\tif i > 0 {
\t\t\t\tline += "/"
\t\t\t}
\t\t\tline += d
\t\t}
\t\tline += "/4#inet#lalune_direct#direct4\n"
\t\tif err := os.WriteFile(directDnsmasqPath, []byte(line), 0644); err != nil {
\t\t\treturn fmt.Errorf("запись dnsmasq direct-конфига: %w", err)
\t\t}
\t\tif err := t.app.runSudo("systemctl restart dnsmasq"); err != nil {
\t\t\treturn fmt.Errorf("перезапуск dnsmasq: %w", err)
\t\t}
\t}

\tif err := t.app.runSudo("ip rule add pref " + directRulePref + " fwmark " + directMark + "/0xffff lookup main"); err != nil {
\t\treturn fmt.Errorf("ip rule Direct: %w", err)
\t}

\tt.app.core.AddLog(fmt.Sprintf("[DIRECT] Активно: доменов=%d, IP/CIDR=%d; mark=%s; LTE=main", len(domains), len(ips), directMark))
\treturn nil
}

func (t *LinuxTun) ApplyDirectRouting() error {
\tt.mu.Lock()
\tdefer t.mu.Unlock()
\treturn t.applyDirectRoutingLocked()
}

func (t *LinuxTun) CleanupDirectRouting() {
\tt.mu.Lock()
\tdefer t.mu.Unlock()
\tt.cleanupDirectRoutingLocked()
}

'''
# This Go fragment originated in a JavaScript patch and contains escaped tabs and
# doubled Go escapes. Normalize it before inserting it into the Go source file.
linux_direct = linux_direct.replace("\\\\", "\\")
_normalized_lines = []
for _line in linux_direct.splitlines():
    _indent = ""
    while _line.startswith("\\t"):
        _indent += "\t"
        _line = _line[2:]
    _normalized_lines.append(_indent + _line)
linux_direct = "\n".join(_normalized_lines) + "\n"

# Integrate direct-domain/IP bypass into the Linux adapter and settings UI.
s = LINUX.read_text()
marker = 'func (t *LinuxTun) SetupRoutes(tunIP, tunDNS string) {'
if s.count(marker) != 1:
    raise SystemExit('SetupRoutes marker missing or ambiguous')
s = s.replace(marker, linux_direct + marker, 1)

setup_old = '\tt.app.runSudo("ip rule add pref 22020 from 192.168.5.0/24 lookup 202")\n\n\tt.app.core.AddLog("[TUN] TUN настроен успешно (policy table 202)")'
setup_new = '\tt.app.runSudo("ip rule add pref 22020 from 192.168.5.0/24 lookup 202")\n\n\tif err := t.applyDirectRoutingLocked(); err != nil {\n\t\tt.app.core.AddLog(fmt.Sprintf("[DIRECT] Ошибка применения: %v", err))\n\t}\n\tt.app.core.AddLog("[TUN] TUN настроен успешно (policy table 202)")'
if s.count(setup_old) != 1:
    raise SystemExit('SetupRoutes body marker missing or ambiguous')
s = s.replace(setup_old, setup_new, 1)

cleanup_old = '\tt.app.core.AddLog("[TUN] Удаление TUN...")\n\tt.app.runSudo("ip rule del pref 22020 2>/dev/null || true")'
cleanup_new = '\tt.app.core.AddLog("[TUN] Удаление TUN...")\n\tt.cleanupDirectRoutingLocked()\n\tt.app.runSudo("ip rule del pref 22020 2>/dev/null || true")'
if s.count(cleanup_old) != 1:
    raise SystemExit('CleanupRoutes marker missing or ambiguous')
s = s.replace(cleanup_old, cleanup_new, 1)
LINUX.write_text(s)

# Add direct routing preferences to the persisted settings model.
s = API_DART.read_text()
replacements = [
    ('''  final bool validateVkHashes;\n\n  /// Экспериментальные функции.''', '''  final bool validateVkHashes;\n  final String directDomains;\n  final String directIPs;\n\n  /// Экспериментальные функции.'''),
    ('''    this.validateVkHashes = false,\n    this.enableSmartTunnel = false,''', '''    this.validateVkHashes = false,\n    this.directDomains = '',\n    this.directIPs = '',\n    this.enableSmartTunnel = false,'''),
    ('''      validateVkHashes: (j['validateVkHashes'] ?? false) as bool,\n      enableSmartTunnel:''', '''      validateVkHashes: (j['validateVkHashes'] ?? false) as bool,\n      directDomains: (j['directDomains'] ?? '') as String,\n      directIPs: (j['directIPs'] ?? '') as String,\n      enableSmartTunnel:'''),
    ('''    'validateVkHashes': validateVkHashes,\n    'enableSmartTunnel': enableSmartTunnel,''', '''    'validateVkHashes': validateVkHashes,\n    'directDomains': directDomains,\n    'directIPs': directIPs,\n    'enableSmartTunnel': enableSmartTunnel,'''),
    ('''    String? vkAuthMode, bool? allowHashRedistribution, bool? validateVkHashes,\n    bool? enableSmartTunnel,''', '''    String? vkAuthMode, bool? allowHashRedistribution, bool? validateVkHashes,\n    String? directDomains, String? directIPs,\n    bool? enableSmartTunnel,'''),
    ('''    validateVkHashes: validateVkHashes ?? this.validateVkHashes,\n    enableSmartTunnel:''', '''    validateVkHashes: validateVkHashes ?? this.validateVkHashes,\n    directDomains: directDomains ?? this.directDomains,\n    directIPs: directIPs ?? this.directIPs,\n    enableSmartTunnel:'''),
]
for old, new in replacements:
    if s.count(old) != 1:
        raise SystemExit(f'API settings marker missing or ambiguous: {old[:80]!r}')
    s = s.replace(old, new, 1)
API_DART.write_text(s)

# Add editable domain and IPv4/CIDR lists to Settings.
s = SETTINGS_PAGE.read_text()
replacements = [
    ('''  final _deviceIdCtl = TextEditingController();''', '''  final _deviceIdCtl = TextEditingController();\n  final _directDomainsCtl = TextEditingController();\n  final _directIPsCtl = TextEditingController();'''),
    ('''    _deviceIdCtl.dispose();''', '''    _deviceIdCtl.dispose();\n    _directDomainsCtl.dispose();\n    _directIPsCtl.dispose();'''),
    ('''    _deviceIdCtl.text = s.deviceId;\n    _authMode''', '''    _deviceIdCtl.text = s.deviceId;\n    _directDomainsCtl.text = s.directDomains;\n    _directIPsCtl.text = s.directIPs;\n    _authMode'''),
    ('''      authMode: _authMode,\n      enableSmartTunnel: _enableSmartTunnel,''', '''      authMode: _authMode,\n      directDomains: _directDomainsCtl.text.trim(),\n      directIPs: _directIPsCtl.text.trim(),\n      enableSmartTunnel: _enableSmartTunnel,'''),
]
for old, new in replacements:
    if s.count(old) != 1:
        raise SystemExit(f'Settings marker missing or ambiguous: {old[:80]!r}')
    s = s.replace(old, new, 1)
ui_marker = '''              const SizedBox(height: 18),\n\n              _sectionTitle('Device ID'),'''
ui_insert = '''              const SizedBox(height: 18),\n\n              _sectionTitle('Direct — обход CSQTT'),\n              GlassCard(\n                child: Column(\n                  crossAxisAlignment: CrossAxisAlignment.start,\n                  children: [\n                    Text('Только указанные назначения идут напрямую через LTE. Всё остальное остаётся через CSQTT.',\n                      style: TextStyle(fontSize: 11.5, height: 1.45, color: Colors.white.withOpacity(0.55))),\n                    const SizedBox(height: 12),\n                    Text('Домены', style: TextStyle(fontSize: 12, color: Colors.white.withOpacity(0.7))),\n                    const SizedBox(height: 5),\n                    TextField(\n                      controller: _directDomainsCtl,\n                      minLines: 3,\n                      maxLines: 8,\n                      style: const TextStyle(fontSize: 13),\n                      decoration: const InputDecoration(hintText: 'example.com\\ncdn.example.com'),\n                      onChanged: (_) => _markDirty(),\n                    ),\n                    const SizedBox(height: 12),\n                    Text('IP / CIDR', style: TextStyle(fontSize: 12, color: Colors.white.withOpacity(0.7))),\n                    const SizedBox(height: 5),\n                    TextField(\n                      controller: _directIPsCtl,\n                      minLines: 3,\n                      maxLines: 8,\n                      style: const TextStyle(fontSize: 13),\n                      decoration: const InputDecoration(hintText: '1.2.3.4\\n1.2.3.0/24'),\n                      onChanged: (_) => _markDirty(),\n                    ),\n                    const SizedBox(height: 7),\n                    Text('По одному значению в строке; также принимаются запятые. Сейчас IPv4.',\n                      style: TextStyle(fontSize: 10.5, color: Colors.white.withOpacity(0.45))),\n                  ],\n                ),\n              ),\n              const SizedBox(height: 18),\n\n              _sectionTitle('Device ID'),'''
if s.count(ui_marker) != 1:
    raise SystemExit('Settings UI insertion marker missing or ambiguous')
SETTINGS_PAGE.write_text(s.replace(ui_marker, ui_insert, 1))

# Make the no-selection state explicit. Without this, deleting the active last
# profile leaves a stale pointer in AppCore and the UI keeps trying to connect it.
COMMON = UPSTREAM / "Desktop/Libs/common.go"
replace_once(
    COMMON,
    '''func (a *AppCore) SetSelectedConfigJson(jsonStr string) bool {
	var c Config
	if err := json.Unmarshal([]byte(jsonStr), &c); err != nil {
		return false
	}
	a.SetSelectedConfig(&c)
	return true
}''',
    '''func (a *AppCore) SetSelectedConfigJson(jsonStr string) bool {
	trimmed := strings.TrimSpace(jsonStr)
	if trimmed == "null" || trimmed == "{}" || trimmed == "" {
		a.SetSelectedConfig(nil)
		return true
	}
	var c Config
	if err := json.Unmarshal([]byte(jsonStr), &c); err != nil {
		return false
	}
	if c.ID <= 0 {
		return false
	}
	a.SetSelectedConfig(&c)
	return true
}'''
)
print('Direct domain/IP bypass and explicit selection clearing adaptations applied')
