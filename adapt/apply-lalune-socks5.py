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

# Add mark policy and start SOCKS5 only after all TUN setup has succeeded.
marker = '\tt.app.core.AddLog("[TUN] TUN настроен успешно (table 202; чужие маршруты и DNS сохранены)")'
addition = '''\tif err := t.app.runSudo("ip rule add pref 22015 fwmark 0x4d53/0xffff lookup 202"); err != nil {
\t\tt.cleanupDirectRoutingLocked()
\t\trollback()
\t\treturn fmt.Errorf("add SOCKS5 fwmark rule: %w", err)
\t}
\tif t.app.socks != nil {
\t\tif err := t.app.socks.Start(); err != nil {
\t\t\t_ = t.app.runSudo("ip rule del pref 22015 fwmark 0x4d53/0xffff lookup 202")
\t\t\tt.cleanupDirectRoutingLocked()
\t\t\trollback()
\t\t\treturn fmt.Errorf("start SOCKS5 listener: %w", err)
\t\t}
\t\tt.app.core.AddLog("[SOCKS5] Listening on :12500; bind address is dynamic")
\t}
'''
if marker not in s:
    raise SystemExit("TUN success marker missing")
s = s.replace(marker, addition + marker, 1)

# Stop the listener and remove its dedicated fwmark rule during TUN cleanup.
marker = '\tt.cleanupDirectRoutingLocked()\n\tt.app.core.AddLog("[TUN] Удаление TUN...")'
replacement = '''\tif t.app.socks != nil { t.app.socks.Stop() }
\tif err := t.app.runSudo("ip rule del pref 22015 fwmark 0x4d53/0xffff lookup 202"); err != nil {
\t\tt.app.core.AddLog(fmt.Sprintf("[SOCKS5] Не удалось удалить fwmark rule: %v", err))
\t}
''' + marker
if marker not in s:
    raise SystemExit("cleanup marker missing")
s = s.replace(marker, replacement, 1)

# Initialize the server in NewApp.
old = '\tapp := &App{core: core, tun: tun}\n'
new = """\tapp := &App{core: core, tun: tun}\n\tlistenAddr, listenErr := laluneSocks5ListenAddr()\n\tif listenErr != nil { app.core.AddLog(fmt.Sprintf("[SOCKS5] Listener не запущен: %v", listenErr)) } else { app.socks = NewSocks5Server(listenAddr) }\n"""
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
