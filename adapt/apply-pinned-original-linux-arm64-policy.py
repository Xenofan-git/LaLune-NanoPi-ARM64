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
	t.mu.Lock()
	defer t.mu.Unlock()
	t.app.core.AddLog(fmt.Sprintf("[TUN] Настройка TUN (IP: %s, DNS: %s)...", tunIP, tunDNS))

	ip := net.ParseIP(strings.TrimSpace(tunIP))
	if ip == nil || ip.To4() == nil {
		t.app.core.AddLog("[TUN] ОШИБКА: некорректный IPv4 TUN; настройка отменена")
		return
	}
	var dnsServers []string
	for _, raw := range strings.Split(tunDNS, ",") {
		d := strings.TrimSpace(raw)
		if d == "" { continue }
		parsed := net.ParseIP(d)
		if parsed == nil || parsed.To4() == nil {
			t.app.core.AddLog(fmt.Sprintf("[TUN] ОШИБКА: некорректный DNS IPv4 %q; настройка отменена", d))
			return
		}
		dnsServers = append(dnsServers, parsed.To4().String())
	}

	// Fail closed if the dedicated table/priority already contains anything.
	// Never flush or replace routes/rules we cannot prove are ours.
	if err := t.app.runSudo("test -z \"$(ip -o route show table 202 2>/dev/null)\" && test -z \"$(ip -o rule show pref 22020 2>/dev/null)\""); err != nil {
		t.app.core.AddLog(fmt.Sprintf("[TUN] ОШИБКА: table 202 или priority 22020 уже заняты; чужие сетевые правила сохранены: %v", err))
		return
	}
	createdTun := false
	rollback := func() {
		if createdTun {
			t.app.runSudo("ip rule del pref 22020 from 192.168.5.0/24 lookup 202 2>/dev/null || true")
			t.app.runSudo("ip route del default dev csqtt0 table 202 2>/dev/null || true")
			t.app.runSudo("ip route del 192.168.5.0/24 dev eth1 table 202 2>/dev/null || true")
			t.app.runSudo("ip route del 192.168.4.0/24 dev eth0 table 202 2>/dev/null || true")
			t.app.runSudo("ip tuntap del dev csqtt0 mode tun 2>/dev/null || true")
			t.app.runSudo("resolvectl revert csqtt0 2>/dev/null || true")
		}
	}
	cmd := fmt.Sprintf("ip tuntap add dev csqtt0 mode tun && ip addr add %s/32 dev csqtt0 && ip link set csqtt0 up && ip link set csqtt0 mtu 1300", ip.To4().String())
	if err := t.app.runSudo(cmd); err != nil {
		t.app.core.AddLog(fmt.Sprintf("[TUN] ОШИБКА создания интерфейса: %v", err))
		return
	}
	createdTun = true
	commands := []string{
		"ip route add 192.168.4.0/24 dev eth0 table 202",
		"ip route add 192.168.5.0/24 dev eth1 table 202",
		"ip route add default dev csqtt0 table 202",
		"ip rule add pref 22020 from 192.168.5.0/24 lookup 202",
	}
	for _, command := range commands {
		if err := t.app.runSudo(command); err != nil {
			t.app.core.AddLog(fmt.Sprintf("[TUN] ОШИБКА команды %q: %v; откат собственных изменений", command, err))
			rollback()
			return
		}
	}
	if len(dnsServers) > 0 {
		if err := t.app.runSudo("resolvectl dns csqtt0 " + strings.Join(dnsServers, " ")); err != nil {
			t.app.core.AddLog(fmt.Sprintf("[TUN] DNS csqtt0 не применён через systemd-resolved (глобальный resolv.conf не изменялся): %v", err))
		}
	}
	t.app.core.AddLog("[TUN] TUN настроен успешно (policy table 202; foreign routes preserved)")
}'''
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

# The upstream token-fetcher release is Linux x64 only. Bundle a native
# linux-arm64 build and let Playwright use Debian's system Chromium on NanoPi.
VTOKEN = UPSTREAM / "Desktop/Libs/vktoken.go"
replace_once(
    VTOKEN,
    'VKTokenFetcherArchive = "LaLuneTokenFetcher_%s.zip"',
    'VKTokenFetcherArchive = "LaLuneTokenFetcher_%s.zip"\n\tVKTokenFetcherARM64Archive = "LaLuneTokenFetcher_Linux_ARM64.zip"',
)
replace_once(
    VTOKEN,
    '// EnsureVKTokenFetcher — скачивает и устанавливает LaLuneTokenFetcher.',
    '''func (a *AppCore) bundledVKTokenFetcherArchive() string {
    candidates := []string{}
    if exe, err := os.Executable(); err == nil {
        candidates = append(candidates, filepath.Join(filepath.Dir(exe), "server-assets", VKTokenFetcherARM64Archive))
    }
    candidates = append(candidates, filepath.Join("/usr/local/lib/lalune/server-assets", VKTokenFetcherARM64Archive))
    for _, candidate := range candidates {
        if info, err := os.Stat(candidate); err == nil && info.Mode().IsRegular() && info.Size() > 0 {
            return candidate
        }
    }
    return ""
}

// EnsureVKTokenFetcher — скачивает и устанавливает LaLuneTokenFetcher.'''
)
replace_once(
    VTOKEN,
    'if !DownloadFile(url, zipPath) {',
    '''if runtime.GOOS == "linux" && runtime.GOARCH == "arm64" {
        bundled := a.bundledVKTokenFetcherArchive()
        if bundled == "" {
            return false, fmt.Errorf("для NanoPi ARM64 не найден bundled LaLuneTokenFetcher_Linux_ARM64.zip")
        }
        data, err := os.ReadFile(bundled)
        if err != nil {
            return false, fmt.Errorf("не удалось прочитать ARM64 token fetcher: %w", err)
        }
        if err := os.WriteFile(zipPath, data, 0600); err != nil {
            return false, fmt.Errorf("не удалось подготовить ARM64 token fetcher: %w", err)
        }
        archiveName = VKTokenFetcherARM64Archive
        a.AddLog(fmt.Sprintf("[VK] Использую локальный ARM64 token fetcher: %s", bundled))
    } else if !DownloadFile(url, zipPath) {'''
)


replace_once(
    VTOKEN,
    '"strings"',
    '"strings"\n\t"net/url"'
)
replace_once(
    VTOKEN,
    'func (a *AppCore) HasVKToken() bool {',
    '''func (a *AppCore) SaveVKTokenInput(value string) error {
    value = strings.TrimSpace(value)
    token := value
    if strings.Contains(value, "://") {
        parsed, err := url.Parse(value)
        if err != nil { return fmt.Errorf("некорректная ссылка OAuth: %w", err) }
        token = parsed.Query().Get("access_token")
        if token == "" && parsed.Fragment != "" {
            fragment, err := url.ParseQuery(parsed.Fragment)
            if err != nil { return fmt.Errorf("не удалось разобрать фрагмент OAuth: %w", err) }
            token = fragment.Get("access_token")
        }
    } else if strings.Contains(value, "access_token=") {
        fragment := strings.TrimPrefix(value, "#")
        parsed, err := url.ParseQuery(fragment)
        if err == nil { token = parsed.Get("access_token") }
    }
    token = strings.TrimSpace(token)
    if len(token) < 20 || strings.ContainsAny(token, " \\t\\r\\n") {
        return fmt.Errorf("не найден корректный access_token; вставьте URL после успешного входа VK или сам токен")
    }
    if err := os.MkdirAll(a.appDir, 0700); err != nil {
        return fmt.Errorf("не удалось создать каталог токена: %w", err)
    }
    data, err := json.MarshalIndent(VKTokenJSON{Token: token, SavedAt: time.Now()}, "", "  ")
    if err != nil { return fmt.Errorf("не удалось сериализовать VK токен: %w", err) }
    if err := os.WriteFile(a.vkTokenFile(), data, 0600); err != nil {
        return fmt.Errorf("не удалось сохранить VK токен: %w", err)
    }
    if err := os.Chmod(a.vkTokenFile(), 0600); err != nil {
        return fmt.Errorf("не удалось ограничить права VK токена: %w", err)
    }
    return nil
}

func (a *AppCore) HasVKToken() bool {'''
)

FETCHER = UPSTREAM / "Core/LaLuneTokenFetcher/Playwright/PlaywrightTokenFetcher.cs"
replace_once(
    FETCHER,
    '                    Headless = false,',
    '                    Headless = OperatingSystem.IsLinux(),\n                    ExecutablePath = ResolveChromiumExecutable(),'
)
replace_once(
    FETCHER,
    '    private static bool IsBrowserMissing(PlaywrightException ex)',
    '''    private static string? ResolveChromiumExecutable()
    {
        if (!OperatingSystem.IsLinux() ||
            System.Runtime.InteropServices.RuntimeInformation.ProcessArchitecture != System.Runtime.InteropServices.Architecture.Arm64)
        {
            return null;
        }

        var configured = Environment.GetEnvironmentVariable("PLAYWRIGHT_CHROMIUM_EXECUTABLE");
        if (!string.IsNullOrWhiteSpace(configured) && File.Exists(configured))
        {
            return configured;
        }

        foreach (var candidate in new[] { "/usr/bin/chromium", "/usr/bin/chromium-browser" })
        {
            if (File.Exists(candidate))
            {
                return candidate;
            }
        }

        throw new ChromiumMissingException(
            "Для VK-авторизации на NanoPi ARM64 нужен системный Chromium. Установите пакет chromium.");
    }

    private static bool IsBrowserMissing(PlaywrightException ex)'''
)

print('Direct domain/IP bypass and explicit selection clearing adaptations applied')cleanup = '''func (t *LinuxTun) CleanupRoutes() {
	t.mu.Lock()
	defer t.mu.Unlock()
	t.app.core.AddLog("[TUN] Удаление TUN...")
	// Delete only exact route/rule tuples owned by this adapter.
	for _, command := range []string{
		"ip rule del pref 22020 from 192.168.5.0/24 lookup 202",
		"ip route del default dev csqtt0 table 202",
		"ip route del 192.168.5.0/24 dev eth1 table 202",
		"ip route del 192.168.4.0/24 dev eth0 table 202",
	} {
		if err := t.app.runSudo(command); err != nil {
			t.app.core.AddLog(fmt.Sprintf("[TUN] Не удалось удалить собственную запись %q: %v", command, err))
		}
	}
	if err := t.app.runSudo("resolvectl revert csqtt0 2>/dev/null || true"); err != nil {
		t.app.core.AddLog(fmt.Sprintf("[TUN] Не удалось отменить DNS csqtt0: %v", err))
	}
	if err := t.app.runSudo("ip tuntap del dev csqtt0 mode tun 2>/dev/null || true"); err != nil {
		t.app.core.AddLog(fmt.Sprintf("[TUN] Не удалось удалить интерфейс csqtt0: %v", err))
	}
	t.app.core.AddLog("[TUN] TUN удалён; чужие маршруты и DNS не изменялись")
}'''
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
	t.mu.Lock()
	defer t.mu.Unlock()
	t.app.core.AddLog(fmt.Sprintf("[TUN] Настройка TUN (IP: %s, DNS: %s)...", tunIP, tunDNS))

	ip := net.ParseIP(strings.TrimSpace(tunIP))
	if ip == nil || ip.To4() == nil {
		t.app.core.AddLog("[TUN] ОШИБКА: некорректный IPv4 TUN; настройка отменена")
		return
	}
	var dnsServers []string
	for _, raw := range strings.Split(tunDNS, ",") {
		d := strings.TrimSpace(raw)
		if d == "" { continue }
		parsed := net.ParseIP(d)
		if parsed == nil || parsed.To4() == nil {
			t.app.core.AddLog(fmt.Sprintf("[TUN] ОШИБКА: некорректный DNS IPv4 %q; настройка отменена", d))
			return
		}
		dnsServers = append(dnsServers, parsed.To4().String())
	}

	// Fail closed if the dedicated table/priority already contains anything.
	// Never flush or replace routes/rules we cannot prove are ours.
	if err := t.app.runSudo("test -z \"$(ip -o route show table 202 2>/dev/null)\" && test -z \"$(ip -o rule show pref 22020 2>/dev/null)\""); err != nil {
		t.app.core.AddLog(fmt.Sprintf("[TUN] ОШИБКА: table 202 или priority 22020 уже заняты; чужие сетевые правила сохранены: %v", err))
		return
	}
	createdTun := false
	rollback := func() {
		if createdTun {
			t.app.runSudo("ip rule del pref 22020 from 192.168.5.0/24 lookup 202 2>/dev/null || true")
			t.app.runSudo("ip route del default dev csqtt0 table 202 2>/dev/null || true")
			t.app.runSudo("ip route del 192.168.5.0/24 dev eth1 table 202 2>/dev/null || true")
			t.app.runSudo("ip route del 192.168.4.0/24 dev eth0 table 202 2>/dev/null || true")
			t.app.runSudo("ip tuntap del dev csqtt0 mode tun 2>/dev/null || true")
			t.app.runSudo("resolvectl revert csqtt0 2>/dev/null || true")
		}
	}
	cmd := fmt.Sprintf("ip tuntap add dev csqtt0 mode tun && ip addr add %s/32 dev csqtt0 && ip link set csqtt0 up && ip link set csqtt0 mtu 1300", ip.To4().String())
	if err := t.app.runSudo(cmd); err != nil {
		t.app.core.AddLog(fmt.Sprintf("[TUN] ОШИБКА создания интерфейса: %v", err))
		return
	}
	createdTun = true
	commands := []string{
		"ip route add 192.168.4.0/24 dev eth0 table 202",
		"ip route add 192.168.5.0/24 dev eth1 table 202",
		"ip route add default dev csqtt0 table 202",
		"ip rule add pref 22020 from 192.168.5.0/24 lookup 202",
	}
	for _, command := range commands {
		if err := t.app.runSudo(command); err != nil {
			t.app.core.AddLog(fmt.Sprintf("[TUN] ОШИБКА команды %q: %v; откат собственных изменений", command, err))
			rollback()
			return
		}
	}
	if len(dnsServers) > 0 {
		if err := t.app.runSudo("resolvectl dns csqtt0 " + strings.Join(dnsServers, " ")); err != nil {
			t.app.core.AddLog(fmt.Sprintf("[TUN] DNS csqtt0 не применён через systemd-resolved (глобальный resolv.conf не изменялся): %v", err))
		}
	}
	t.app.core.AddLog("[TUN] TUN настроен успешно (policy table 202; foreign routes preserved)")
}'''
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

# The upstream token-fetcher release is Linux x64 only. Bundle a native
# linux-arm64 build and let Playwright use Debian's system Chromium on NanoPi.
VTOKEN = UPSTREAM / "Desktop/Libs/vktoken.go"
replace_once(
    VTOKEN,
    'VKTokenFetcherArchive = "LaLuneTokenFetcher_%s.zip"',
    'VKTokenFetcherArchive = "LaLuneTokenFetcher_%s.zip"\n\tVKTokenFetcherARM64Archive = "LaLuneTokenFetcher_Linux_ARM64.zip"',
)
replace_once(
    VTOKEN,
    '// EnsureVKTokenFetcher — скачивает и устанавливает LaLuneTokenFetcher.',
    '''func (a *AppCore) bundledVKTokenFetcherArchive() string {
    candidates := []string{}
    if exe, err := os.Executable(); err == nil {
        candidates = append(candidates, filepath.Join(filepath.Dir(exe), "server-assets", VKTokenFetcherARM64Archive))
    }
    candidates = append(candidates, filepath.Join("/usr/local/lib/lalune/server-assets", VKTokenFetcherARM64Archive))
    for _, candidate := range candidates {
        if info, err := os.Stat(candidate); err == nil && info.Mode().IsRegular() && info.Size() > 0 {
            return candidate
        }
    }
    return ""
}

// EnsureVKTokenFetcher — скачивает и устанавливает LaLuneTokenFetcher.'''
)
replace_once(
    VTOKEN,
    'if !DownloadFile(url, zipPath) {',
    '''if runtime.GOOS == "linux" && runtime.GOARCH == "arm64" {
        bundled := a.bundledVKTokenFetcherArchive()
        if bundled == "" {
            return false, fmt.Errorf("для NanoPi ARM64 не найден bundled LaLuneTokenFetcher_Linux_ARM64.zip")
        }
        data, err := os.ReadFile(bundled)
        if err != nil {
            return false, fmt.Errorf("не удалось прочитать ARM64 token fetcher: %w", err)
        }
        if err := os.WriteFile(zipPath, data, 0600); err != nil {
            return false, fmt.Errorf("не удалось подготовить ARM64 token fetcher: %w", err)
        }
        archiveName = VKTokenFetcherARM64Archive
        a.AddLog(fmt.Sprintf("[VK] Использую локальный ARM64 token fetcher: %s", bundled))
    } else if !DownloadFile(url, zipPath) {'''
)


replace_once(
    VTOKEN,
    '"strings"',
    '"strings"\n\t"net/url"'
)
replace_once(
    VTOKEN,
    'func (a *AppCore) HasVKToken() bool {',
    '''func (a *AppCore) SaveVKTokenInput(value string) error {
    value = strings.TrimSpace(value)
    token := value
    if strings.Contains(value, "://") {
        parsed, err := url.Parse(value)
        if err != nil { return fmt.Errorf("некорректная ссылка OAuth: %w", err) }
        token = parsed.Query().Get("access_token")
        if token == "" && parsed.Fragment != "" {
            fragment, err := url.ParseQuery(parsed.Fragment)
            if err != nil { return fmt.Errorf("не удалось разобрать фрагмент OAuth: %w", err) }
            token = fragment.Get("access_token")
        }
    } else if strings.Contains(value, "access_token=") {
        fragment := strings.TrimPrefix(value, "#")
        parsed, err := url.ParseQuery(fragment)
        if err == nil { token = parsed.Get("access_token") }
    }
    token = strings.TrimSpace(token)
    if len(token) < 20 || strings.ContainsAny(token, " \\t\\r\\n") {
        return fmt.Errorf("не найден корректный access_token; вставьте URL после успешного входа VK или сам токен")
    }
    if err := os.MkdirAll(a.appDir, 0700); err != nil {
        return fmt.Errorf("не удалось создать каталог токена: %w", err)
    }
    data, err := json.MarshalIndent(VKTokenJSON{Token: token, SavedAt: time.Now()}, "", "  ")
    if err != nil { return fmt.Errorf("не удалось сериализовать VK токен: %w", err) }
    if err := os.WriteFile(a.vkTokenFile(), data, 0600); err != nil {
        return fmt.Errorf("не удалось сохранить VK токен: %w", err)
    }
    if err := os.Chmod(a.vkTokenFile(), 0600); err != nil {
        return fmt.Errorf("не удалось ограничить права VK токена: %w", err)
    }
    return nil
}

func (a *AppCore) HasVKToken() bool {'''
)

FETCHER = UPSTREAM / "Core/LaLuneTokenFetcher/Playwright/PlaywrightTokenFetcher.cs"
replace_once(
    FETCHER,
    '                    Headless = false,',
    '                    Headless = OperatingSystem.IsLinux(),\n                    ExecutablePath = ResolveChromiumExecutable(),'
)
replace_once(
    FETCHER,
    '    private static bool IsBrowserMissing(PlaywrightException ex)',
    '''    private static string? ResolveChromiumExecutable()
    {
        if (!OperatingSystem.IsLinux() ||
            System.Runtime.InteropServices.RuntimeInformation.ProcessArchitecture != System.Runtime.InteropServices.Architecture.Arm64)
        {
            return null;
        }

        var configured = Environment.GetEnvironmentVariable("PLAYWRIGHT_CHROMIUM_EXECUTABLE");
        if (!string.IsNullOrWhiteSpace(configured) && File.Exists(configured))
        {
            return configured;
        }

        foreach (var candidate in new[] { "/usr/bin/chromium", "/usr/bin/chromium-browser" })
        {
            if (File.Exists(candidate))
            {
                return candidate;
            }
        }

        throw new ChromiumMissingException(
            "Для VK-авторизации на NanoPi ARM64 нужен системный Chromium. Установите пакет chromium.");
    }

    private static bool IsBrowserMissing(PlaywrightException ex)'''
)

print('Direct domain/IP bypass and explicit selection clearing adaptations applied')
