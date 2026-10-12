//go:build linux

package main

import (
	"net"
	"os"
	"testing"
	"time"

	libs "lalune-desktop/Libs"
)

// This integration test is intended for the disposable Linux ARM64 VM.
// It does not configure routes or resolver state. If the guest does not expose
// a usable /dev/net/tun with CAP_NET_ADMIN, it skips rather than touching host
// networking or attempting privileged setup elsewhere.
func TestLinuxTunBridgeStopUnblocksPacketWorkers(t *testing.T) {
	if _, err := os.Stat("/dev/net/tun"); err != nil {
		t.Skipf("guest has no /dev/net/tun: %v", err)
	}

	core := libs.NewAppCore()
	app := &App{core: core}
	tun := &LinuxTun{app: app}

	udpListener, err := net.ListenUDP("udp", &net.UDPAddr{IP: net.ParseIP("127.0.0.1"), Port: 0})
	if err != nil {
		t.Fatalf("listen UDP: %v", err)
	}
	defer udpListener.Close()

	udpConn, err := net.Dial("udp", udpListener.LocalAddr().String())
	if err != nil {
		t.Fatalf("dial UDP: %v", err)
	}

	running := true
	if err := tun.StartWithError(udpConn, &running); err != nil {
		_ = udpConn.Close()
		t.Skipf("guest cannot create csqtt0 TUN interface (likely missing CAP_NET_ADMIN): %v", err)
	}

	tun.mu.Lock()
	firstFile := tun.tunFile
	tun.mu.Unlock()
	if firstFile == nil {
		t.Fatal("StartWithError succeeded without retaining TUN file")
	}

	// Closing both endpoints must unblock the packet workers.
	running = false
	tun.Stop()
	_ = udpConn.Close()

	deadline := time.Now().Add(2 * time.Second)
	for time.Now().Before(deadline) {
		tun.mu.Lock()
		file := tun.tunFile
		tun.mu.Unlock()
		if file == nil {
			return
		}
		time.Sleep(10 * time.Millisecond)
	}
	t.Fatal("TUN file remained owned after Stop")
}
