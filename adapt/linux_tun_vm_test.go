//go:build linux

package main

import (
	"errors"
	"net"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"golang.org/x/sys/unix"

	libs "lalune-desktop/Libs"
)

// These tests execute the generated LinuxTun.SetupRoutes implementation with
// command shims. They run inside the disposable ARM64 system VM and never touch
// host routes, interfaces, resolver state, or Direct policy.
func tunTestApp() *App {
	core := libs.NewAppCore()
	tun := &LinuxTun{}
	app := &App{core: core, tun: tun}
	tun.app = app
	return app
}

func installTunCommandShims(t *testing.T, failContains string) string {
	t.Helper()
	dir := t.TempDir()
	logPath := filepath.Join(dir, "commands.log")
	sudo := "#!/bin/sh\nprintf 'SUDO %s\\n' \"$*\" >> \"" + logPath + "\"\n" +
		"if [ -n \"${FAKE_SUDO_FAIL_CONTAINS:-}\" ]; then case \"$*\" in *\"$FAKE_SUDO_FAIL_CONTAINS\"*) exit 17;; esac; fi\nif [ \"$1\" = test ]; then shift; /usr/bin/test \"$@\"; exit $?; fi\nexit 0\n"
	ip := "#!/bin/sh\nprintf 'IP %s\\n' \"$*\" >> \"" + logPath + "\"\n" +
		"case \"$*\" in\n" +
		"  '-o route show table 202') [ -n \"${FAKE_IP_OCCUPIED_ROUTE:-}\" ] && echo \"$FAKE_IP_OCCUPIED_ROUTE\";;\n" +
		"  '-o rule show pref 22020') [ -n \"${FAKE_IP_OCCUPIED_RULE:-}\" ] && echo \"$FAKE_IP_OCCUPIED_RULE\";;\n" +
		"esac\nexit 0\n"
	for name, content := range map[string]string{"sudo": sudo, "ip": ip} {
		path := filepath.Join(dir, name)
		if err := os.WriteFile(path, []byte(content), 0700); err != nil {
			t.Fatal(err)
		}
	}
	t.Setenv("PATH", dir+string(os.PathListSeparator)+os.Getenv("PATH"))
	t.Setenv("FAKE_SUDO_LOG", logPath)
	t.Setenv("FAKE_SUDO_FAIL_CONTAINS", failContains)
	return logPath
}

func readTunCommandLog(t *testing.T, path string) string {
	t.Helper()
	data, err := os.ReadFile(path)
	if os.IsNotExist(err) {
		return ""
	}
	if err != nil {
		t.Fatal(err)
	}
	return string(data)
}

func TestLinuxTunRejectsInvalidConfigBeforeMutation(t *testing.T) {
	logPath := installTunCommandShims(t, "")
	app := tunTestApp()
	if err := app.tun.SetupRoutes("not-an-ip", "8.8.8.8"); err == nil {
		t.Fatal("invalid TUN address unexpectedly accepted")
	}
	if got := readTunCommandLog(t, logPath); strings.Contains(got, "SUDO ip tuntap add") {
		t.Fatalf("invalid config mutated system state: %s", got)
	}
	if err := app.tun.SetupRoutes("192.0.2.10", "8.8.8.8,not-a-dns"); err == nil {
		t.Fatal("invalid DNS unexpectedly accepted")
	}
	if got := readTunCommandLog(t, logPath); strings.Contains(got, "SUDO ip tuntap add") {
		t.Fatalf("invalid DNS mutated system state: %s", got)
	}
}

func isolateDirectFilesystem(t *testing.T) {
	t.Helper()
	dir := t.TempDir()
	oldNft, oldDnsmasq, oldMain := directNftPath, directDnsmasqPath, directDnsmasqMain
	directNftPath = filepath.Join(dir, "lalune-direct.nft")
	directDnsmasqPath = filepath.Join(dir, "dnsmasq.d", "lalune-direct.conf")
	directDnsmasqMain = filepath.Join(dir, "dnsmasq.conf")
	if err := os.MkdirAll(filepath.Dir(directDnsmasqPath), 0700); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(directDnsmasqMain, []byte("# isolated test config\\n"), 0600); err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() {
		directNftPath, directDnsmasqPath, directDnsmasqMain = oldNft, oldDnsmasq, oldMain
	})
}

func TestLinuxTunSuccessfulSetupBuildsIsolatedPolicy(t *testing.T) {
	logPath := installTunCommandShims(t, "")
	isolateDirectFilesystem(t)
	app := tunTestApp()
	if err := app.tun.SetupRoutes("192.0.2.10", "8.8.8.8,1.1.1.1"); err != nil {
		t.Fatalf("valid TUN setup failed: %v", err)
	}
	log := readTunCommandLog(t, logPath)
	for _, required := range []string{
		"SUDO ip tuntap add dev csqtt0 mode tun",
		"SUDO ip route add 192.168.4.0/24 dev eth0 table 202",
		"SUDO ip route add 192.168.5.0/24 dev eth1 table 202",
		"SUDO ip route add default dev csqtt0 table 202",
		"SUDO ip rule add pref 22020 from 192.168.5.0/24 lookup 202",
		"SUDO resolvectl dns csqtt0 8.8.8.8 1.1.1.1",
	} {
		if !strings.Contains(log, required) {
			t.Fatalf("successful setup trace missing %q:\\n%s", required, log)
		}
	}
	if strings.Contains(log, "SUDO ip route add default dev csqtt0\n") {
		t.Fatalf("setup installed a global default route instead of table 202:\\n%s", log)
	}
	// Applying an empty Direct plan deliberately reconciles that separate policy;
	// the assertions above are limited to the CSQTT route table and DNS scope.
}

func TestLinuxTunCleanupRefusesUnownedState(t *testing.T) {
	logPath := installTunCommandShims(t, "")
	app := tunTestApp()
	// The shims report no CSQTT-owned rule/default route. Cleanup must be a no-op.
	app.tun.CleanupRoutes()
	log := readTunCommandLog(t, logPath)
	if strings.Contains(log, "SUDO ip rule del pref 22020") ||
		strings.Contains(log, "SUDO ip route del default dev csqtt0 table 202") ||
		strings.Contains(log, "SUDO ip tuntap del dev csqtt0 mode tun") {
		t.Fatalf("cleanup touched unowned TUN state:\\n%s", log)
	}
	if !strings.Contains(log, "SUDO ip rule show pref 22020") {
		t.Fatalf("cleanup did not verify ownership before mutation:\\n%s", log)
	}
	assertNoDirectCleanup(t, log)
}

func TestLinuxTunRefusesForeignTableOrRule(t *testing.T) {
	t.Run("foreign route table", func(t *testing.T) {
		logPath := installTunCommandShims(t, "")
		t.Setenv("FAKE_IP_OCCUPIED_ROUTE", "blackhole 198.18.77.0/24")
		app := tunTestApp()
		if err := app.tun.SetupRoutes("192.0.2.10", "8.8.8.8"); err == nil {
			t.Fatal("occupied route table unexpectedly accepted")
		}
		if got := readTunCommandLog(t, logPath); strings.Contains(got, "SUDO ip tuntap add") {
			t.Fatalf("foreign table caused mutation: %s", got)
		}
	})
	t.Run("foreign rule priority", func(t *testing.T) {
		logPath := installTunCommandShims(t, "")
		t.Setenv("FAKE_IP_OCCUPIED_RULE", "22020: from all lookup 42424")
		app := tunTestApp()
		if err := app.tun.SetupRoutes("192.0.2.10", "8.8.8.8"); err == nil {
			t.Fatal("occupied rule priority unexpectedly accepted")
		}
		if got := readTunCommandLog(t, logPath); strings.Contains(got, "SUDO ip tuntap add") {
			t.Fatalf("foreign rule caused mutation: %s", got)
		}
	})
}

func assertNoDirectCleanup(t *testing.T, log string) {
	t.Helper()
	for _, forbidden := range []string{"22010", "lalune_direct", "lalune-direct.nft", "dnsmasq"} {
		if strings.Contains(log, forbidden) {
			t.Fatalf("TUN rollback touched independent Direct policy (%q):\n%s", forbidden, log)
		}
	}
}

func TestLinuxTunRouteFailureRollsBackOnlyOwnedResources(t *testing.T) {
	logPath := installTunCommandShims(t, "ip route add 192.168.5.0/24 dev eth1 table 202")
	app := tunTestApp()
	if err := app.tun.SetupRoutes("192.0.2.10", "8.8.8.8"); err == nil {
		t.Fatal("injected route failure unexpectedly succeeded")
	}
	log := readTunCommandLog(t, logPath)
	for _, required := range []string{
		"SUDO ip tuntap add dev csqtt0 mode tun",
		"SUDO ip route add 192.168.4.0/24 dev eth0 table 202",
		"SUDO ip route del 192.168.4.0/24 dev eth0 table 202",
		"SUDO resolvectl revert csqtt0",
		"SUDO ip tuntap del dev csqtt0 mode tun",
	} {
		if !strings.Contains(log, required) {
			t.Fatalf("rollback trace missing %q:\n%s", required, log)
		}
	}
	if strings.Contains(log, "SUDO ip rule add pref 22020") {
		t.Fatalf("policy rule added after route failure:\n%s", log)
	}
	assertNoDirectCleanup(t, log)
}

func TestLinuxTunDNSFailureRollsBackAndPreservesDirect(t *testing.T) {
	logPath := installTunCommandShims(t, "resolvectl dns csqtt0")
	app := tunTestApp()
	if err := app.tun.SetupRoutes("192.0.2.10", "8.8.8.8,1.1.1.1"); err == nil {
		t.Fatal("injected DNS failure unexpectedly succeeded")
	}
	log := readTunCommandLog(t, logPath)
	for _, required := range []string{
		"SUDO ip route add default dev csqtt0 table 202",
		"SUDO ip rule add pref 22020 from 192.168.5.0/24 lookup 202",
		"SUDO resolvectl dns csqtt0 8.8.8.8 1.1.1.1",
		"SUDO ip rule del pref 22020 from 192.168.5.0/24 lookup 202",
		"SUDO ip route del default dev csqtt0 table 202",
		"SUDO ip route del 192.168.5.0/24 dev eth1 table 202",
		"SUDO ip route del 192.168.4.0/24 dev eth0 table 202",
		"SUDO resolvectl revert csqtt0",
		"SUDO ip tuntap del dev csqtt0 mode tun",
	} {
		if !strings.Contains(log, required) {
			t.Fatalf("DNS rollback trace missing %q:\n%s", required, log)
		}
	}
	assertNoDirectCleanup(t, log)
}


type failingStartTun struct {
	startCalled bool
	stopCalled  bool
}

func (t *failingStartTun) Setup() error { return nil }
func (t *failingStartTun) Start(net.Conn, *bool) { t.startCalled = true }
func (t *failingStartTun) StartWithError(net.Conn, *bool) error {
	return errors.New("injected TUNSETIFF failure")
}
func (t *failingStartTun) Stop() { t.stopCalled = true }
func (t *failingStartTun) SetupRoutes(string, string) error { return nil }
func (t *failingStartTun) CleanupRoutes() {}

func TestBridgeStartTunnelFailsClosedOnTUNStartError(t *testing.T) {
	listener, err := net.ListenUDP("udp", &net.UDPAddr{IP: net.ParseIP("127.0.0.1"), Port: 0})
	if err != nil { t.Fatalf("listen UDP: %v", err) }
	defer listener.Close()

	tun := &failingStartTun{}
	core := libs.NewAppCore()
	core.SetConnected(true)
	bridge := libs.NewBridge(core, tun, nil)
	if bridge.StartTunnel(listener.LocalAddr().(*net.UDPAddr).Port) {
		t.Fatal("StartTunnel unexpectedly reported success after injected TUN startup failure")
	}
	if bridge.TunRunning { t.Fatal("TunRunning remained true after failed startup") }
	if bridge.UdpConn != nil { t.Fatal("UDP connection was retained after failed startup") }
	if core.IsConnected() { t.Fatal("core remained connected after failed TUN startup") }
	if !tun.stopCalled { t.Fatal("TUN Stop was not called during rollback") }
	if tun.startCalled { t.Fatal("legacy non-error Start method used despite error-aware starter") }
}

func TestBridgeStartTunnelRejectsInvalidUDPPort(t *testing.T) {
	tun := &failingStartTun{}
	core := libs.NewAppCore()
	core.SetConnected(true)
	bridge := libs.NewBridge(core, tun, nil)
	if bridge.StartTunnel(70000) {
		t.Fatal("StartTunnel unexpectedly accepted invalid UDP port")
	}
	if bridge.TunRunning { t.Fatal("TunRunning set after UDP dial failure") }
	if bridge.UdpConn != nil { t.Fatal("UDP connection retained after UDP dial failure") }
	if tun.startCalled || tun.stopCalled { t.Fatal("TUN was touched after UDP dial failed") }
}

type successfulStartTun struct {
	starts int
	stops  int
}

func (t *successfulStartTun) Setup() error { return nil }
func (t *successfulStartTun) Start(net.Conn, *bool) {}
func (t *successfulStartTun) StartWithError(net.Conn, *bool) error {
	t.starts++
	return nil
}
func (t *successfulStartTun) Stop() { t.stops++ }
func (t *successfulStartTun) SetupRoutes(string, string) error { return nil }
func (t *successfulStartTun) CleanupRoutes() {}

func TestBridgeStartTunnelReconnectLifecycle(t *testing.T) {
	listener, err := net.ListenUDP("udp", &net.UDPAddr{IP: net.ParseIP("127.0.0.1"), Port: 0})
	if err != nil {
		t.Fatalf("listen UDP: %v", err)
	}
	defer listener.Close()
	port := listener.LocalAddr().(*net.UDPAddr).Port

	tun := &successfulStartTun{}
	core := libs.NewAppCore()
	bridge := libs.NewBridge(core, tun, nil)

	if !bridge.StartTunnel(port) {
		t.Fatal("first StartTunnel unexpectedly failed")
	}
	firstConn := bridge.UdpConn
	if firstConn == nil || !bridge.TunRunning {
		t.Fatal("first start did not retain active UDP connection/running state")
	}
	if !bridge.StartTunnel(port) {
		t.Fatal("repeated StartTunnel while running should be idempotent")
	}
	if tun.starts != 1 {
		t.Fatalf("repeated start initialized TUN %d times; want 1", tun.starts)
	}
	if bridge.UdpConn != firstConn {
		t.Fatal("repeated start replaced the active UDP connection")
	}

	bridge.StopTunnel()
	if bridge.TunRunning || bridge.UdpConn != nil || bridge.TunSetupDone {
		t.Fatal("StopTunnel did not clear running/connection/setup state")
	}
	if tun.stops != 1 {
		t.Fatalf("StopTunnel called TUN Stop %d times; want 1", tun.stops)
	}
	if _, err := firstConn.Write([]byte("after-close")); err == nil {
		t.Fatal("UDP connection remained writable after StopTunnel")
	}

	if !bridge.StartTunnel(port) {
		t.Fatal("StartTunnel failed after disconnect")
	}
	secondConn := bridge.UdpConn
	if secondConn == nil || secondConn == firstConn {
		t.Fatal("reconnect did not create a fresh UDP connection")
	}
	if tun.starts != 2 {
		t.Fatalf("reconnect initialized TUN %d times total; want 2", tun.starts)
	}
	bridge.StopTunnel()
	if bridge.TunRunning || bridge.UdpConn != nil || tun.stops != 2 {
		t.Fatal("second disconnect did not release tunnel state")
	}
}


// These lifecycle tests use injected file/ioctl operations; they never require
// /dev/net/tun or mutate host networking.
func TestLinuxTunOpenFailureIsReturned(t *testing.T) {
	app := tunTestApp()
	app.tun.tunOpen = func() (*os.File, error) { return nil, os.ErrPermission }
	left, right := net.Pipe()
	defer left.Close()
	defer right.Close()
	if err := app.tun.StartWithError(left, new(bool)); err == nil || !strings.Contains(err.Error(), "open /dev/net/tun") {
		t.Fatalf("expected surfaced TUN open error, got %v", err)
	}
	if app.tun.tunFile != nil { t.Fatal("TUN file retained after open failure") }
}

func TestLinuxTunSetIFFFailureClosesOpenedFile(t *testing.T) {
	app := tunTestApp()
	f, err := os.CreateTemp(t.TempDir(), "fake-tun")
	if err != nil { t.Fatal(err) }
	app.tun.tunOpen = func() (*os.File, error) { return f, nil }
	app.tun.tunSetIFF = func(*os.File, *unix.Ifreq) error { return errors.New("injected TUNSETIFF failure") }
	left, right := net.Pipe()
	defer left.Close()
	defer right.Close()
	if err := app.tun.StartWithError(left, new(bool)); err == nil || !strings.Contains(err.Error(), "TUNSETIFF") {
		t.Fatalf("expected surfaced TUNSETIFF error, got %v", err)
	}
	if _, err := f.Stat(); err == nil { t.Fatal("file remained open after TUNSETIFF failure") }
	if app.tun.tunFile != nil { t.Fatal("TUN file retained after TUNSETIFF failure") }
}

func TestLinuxTunStopJoinsWorkersAndIsIdempotent(t *testing.T) {
	app := tunTestApp()
	f, err := os.CreateTemp(t.TempDir(), "fake-tun")
	if err != nil { t.Fatal(err) }
	app.tun.tunOpen = func() (*os.File, error) { return f, nil }
	app.tun.tunSetIFF = func(*os.File, *unix.Ifreq) error { return nil }
	left, right := net.Pipe()
	defer right.Close()
	if err := app.tun.StartWithError(left, new(bool)); err != nil { t.Fatalf("start: %v", err) }
	app.tun.Stop()
	if _, err := f.Stat(); err == nil { t.Fatal("TUN file remained open after Stop") }
	if app.tun.tunFile != nil || app.tun.udpConn != nil { t.Fatal("Stop retained resource references") }
	app.tun.Stop()
	app.tun.workers.Wait()
}
