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
addition = '''\tif t.app.socks != nil {
\t\tif err := t.app.runSudo("ip rule add pref 22015 fwmark 0x4d53/0xffff lookup 202"); err != nil {
\t\t\tt.cleanupDirectRoutingLocked()
\t\t\trollback()
\t\t\treturn fmt.Errorf("add SOCKS5 fwmark rule: %w", err)
\t\t}
\t\tt.socksRuleCreated = true
\t\tif err := t.app.socks.Start(); err != nil {
\t\t\tif cleanupErr := t.app.runSudo("ip rule del pref 22015 fwmark 0x4d53/0xffff lookup 202"); cleanupErr != nil {
\t\t\t\tt.app.core.AddLog(fmt.Sprintf("[SOCKS5] Failed to rollback fwmark rule: %v", cleanupErr))
\t\t\t} else {
\t\t\t\tt.socksRuleCreated = false
\t\t\t}
\t\t\tt.cleanupDirectRoutingLocked()
\t\t\trollback()
\t\t\treturn fmt.Errorf("start SOCKS5 listener: %w", err)
\t\t}
\t\tt.app.core.AddLog("[SOCKS5] Address monitor started; waiting for eth1 private IPv4 or rebinding dynamically")
\t}
'''
if marker not in s:
    raise SystemExit("TUN success marker missing")
s = s.replace(marker, addition + marker, 1)

# Stop the listener and remove its dedicated fwmark rule during TUN cleanup.
marker = '\tdefer t.mu.Unlock()\n\t// Do not remove matching-looking entries unless the complete CSQTT route\n\t// signature is present.'
replacement = '''\tdefer t.mu.Unlock()
\t// SOCKS5 is an independent listener lifecycle: stop it even when the TUN
\t// ownership signature is incomplete and route cleanup must be skipped.
\tif t.app.socks != nil { t.app.socks.Stop() }
\tif t.socksRuleCreated {
\t\tif err := t.app.runSudo("ip rule del pref 22015 fwmark 0x4d53/0xffff lookup 202"); err != nil {
\t\t\tt.app.core.AddLog(fmt.Sprintf("[SOCKS5] Не удалось удалить fwmark rule: %v", err))
\t\t} else {
\t\t\tt.socksRuleCreated = false
\t\t}
\t}
\t// Do not remove matching-looking entries unless the complete CSQTT route
\t// ownership signature is present.'''
if marker not in s:
    raise SystemExit("cleanup marker missing")
s = s.replace(marker, replacement, 1)

# Initialize the server in NewApp.
old = '\tapp := &App{core: core, tun: tun}\n'
new = """\tapp := &App{core: core, tun: tun}\n\t// Resolve eth1 dynamically when TUN starts and rebind after DHCP/address changes.\n\tapp.socks = NewSocks5Server("eth1:12500")\n"""
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
