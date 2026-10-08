from pathlib import Path

ROOT = Path("upstream-lalune")
src = ROOT / "Desktop/Linux/app_linux.go"
s = src.read_text()

# Add SOCKS5 server to App.
old = "\trunner    *LinuxRunner\n"
new = "\trunner    *LinuxRunner\n\tsocks      *Socks5Server\n"
if old not in s:
    raise SystemExit("missing App runner field")
s = s.replace(old, new, 1)

# Start SOCKS5 only after the LaLune TUN/policy table is ready.
old = '\tapp.runSudo("ip rule add pref 22020 from 192.168.5.0/24 lookup 202")\n'
new = old + '\tapp.runSudo("ip rule add pref 22015 fwmark 0x4c4c/0xffff lookup 202")\n\tif t.app.socks != nil {\n\t\tif err := t.app.socks.Start(); err != nil { t.app.core.AddLog(fmt.Sprintf("[SOCKS5] Ошибка запуска: %v", err)) } else { t.app.core.AddLog("[SOCKS5] LaLune SOCKS5: 192.168.4.26:12500") }\n\t}\n'
if old not in s:
    raise SystemExit("missing policy rule marker")
s = s.replace(old, new, 1)

# Stop SOCKS5 and remove its fwmark rule during cleanup.
old = '\tt.app.runSudo("ip rule del pref 22020 2>/dev/null || true")\n'
new = '\tif t.app.socks != nil { t.app.socks.Stop() }\n\tt.app.runSudo("ip rule del pref 22015 2>/dev/null || true")\n' + old
if old not in s:
    raise SystemExit("missing cleanup rule marker")
s = s.replace(old, new, 1)

# Initialize the server in NewApp.
old = '\tapp := &App{core: core, tun: tun}\n'
new = '\tapp := &App{core: core, tun: tun}\n\tapp.socks = NewSocks5Server("192.168.4.26:12500")\n'
if old not in s:
    raise SystemExit("missing NewApp marker")
s = s.replace(old, new, 1)

# The SOCKS server must not remain active after explicit Disconnect.
old = '\tresult := a.bridge.Disconnect()\n\ta.tun.CleanupRoutes()\n'
new = '\tresult := a.bridge.Disconnect()\n\ta.tun.CleanupRoutes()\n'
# no-op: CleanupRoutes owns SOCKS shutdown.

src.write_text(s)

helper = ROOT / "Desktop/Linux/lalune_socks5_linux.go"
helper.write_text(Path("adapt/lalune_socks5_linux.go").read_text())
print("LaLune SOCKS5 adaptation applied")
