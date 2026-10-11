//go:build linux

package main

import (
	"os"
	"path/filepath"
	"strings"
	"testing"

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
