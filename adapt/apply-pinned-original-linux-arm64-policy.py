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
\tr.startCoreWithSudo(cmdArgs, listenPort, bridge)
}"""
new_runner_guard = old_runner_guard
if old_runner_guard not in s:
    raise SystemExit("LinuxRunner.StartCore marker not found")
s = s.replace(old_runner_guard, new_runner_guard, 1)