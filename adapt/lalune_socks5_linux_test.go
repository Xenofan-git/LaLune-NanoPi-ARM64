//go:build linux

package main

import (
	"encoding/binary"
	"io"
	"net"
	"strconv"
	"testing"
	"time"
)

func TestWriteSocksReplyUsesDynamicIPv4Address(t *testing.T) {
	server, client := net.Pipe()
	defer server.Close()
	defer client.Close()

	wantIP := net.IPv4(10, 67, 68, 9)
	wantPort := 43127
	done := make(chan error, 1)
	go func() { done <- writeSocksReply(server, 0, &net.TCPAddr{IP: wantIP, Port: wantPort}) }()

	reply := make([]byte, 10)
	if _, err := io.ReadFull(client, reply); err != nil {
		t.Fatal(err)
	}
	if err := <-done; err != nil {
		t.Fatal(err)
	}
	if reply[0] != 5 || reply[1] != 0 || reply[2] != 0 || reply[3] != 1 {
		t.Fatalf("unexpected SOCKS5 reply header: %v", reply[:4])
	}
	if !net.IP(reply[4:8]).Equal(wantIP) {
		t.Fatalf("reply IP = %v, want %v", net.IP(reply[4:8]), wantIP)
	}
	if got := int(binary.BigEndian.Uint16(reply[8:10])); got != wantPort {
		t.Fatalf("reply port = %d, want %d", got, wantPort)
	}
}

func TestSocks5RejectsGreetingWithoutNoAuth(t *testing.T) {
	serverConn, clientConn := net.Pipe()
	defer clientConn.Close()
	s := NewSocks5Server(":0")
	go s.handle(serverConn)

	if _, err := clientConn.Write([]byte{5, 1, 2}); err != nil {
		t.Fatal(err)
	}
	reply := make([]byte, 2)
	if _, err := io.ReadFull(clientConn, reply); err != nil {
		t.Fatal(err)
	}
	if reply[0] != 5 || reply[1] != 0xff {
		t.Fatalf("greeting reply = %v, want [5 255]", reply)
	}
}

func TestReadUDPAddrDomainAndPort(t *testing.T) {
	packet := []byte{3, 11, 'e', 'x', 'a', 'm', 'p', 'l', 'e', '.', 'c', 'o', 'm', 0x30, 0x39}
	got, next, err := readUDPAddr(packet, 0)
	if err != nil {
		t.Fatal(err)
	}
	if got != "example.com:12345" {
		t.Fatalf("address = %q, want example.com:12345", got)
	}
	if next != len(packet) {
		t.Fatalf("next offset = %d, want %d", next, len(packet))
	}
}

func TestReadUDPAddrRejectsTruncatedPacket(t *testing.T) {
	if _, _, err := readUDPAddr([]byte{1, 127, 0}, 0); err == nil {
		t.Fatal("expected truncated address to fail")
	}
}

func TestSocks5ServerStartStopIsIdempotent(t *testing.T) {
	s := NewSocks5Server("127.0.0.1:0")
	if err := s.Start(); err != nil {
		t.Fatalf("first Start: %v", err)
	}
	if err := s.Start(); err != nil {
		t.Fatalf("second Start: %v", err)
	}
	s.Stop()
	s.Stop()
	if err := s.Start(); err != nil {
		t.Fatalf("Start after Stop: %v", err)
	}
	s.Stop()
}

func TestBuildUDPReplyIPv4(t *testing.T) {
	payload := []byte("reply")
	got, err := buildUDPReply(&net.UDPAddr{IP: net.IPv4(192, 0, 2, 10), Port: 5353}, payload)
	if err != nil { t.Fatal(err) }
	wantHeader := []byte{0, 0, 0, 1, 192, 0, 2, 10, 0x14, 0xe9}
	if len(got) != len(wantHeader)+len(payload) { t.Fatalf("packet length = %d", len(got)) }
	for i := range wantHeader { if got[i] != wantHeader[i] { t.Fatalf("header = %v, want %v", got[:len(wantHeader)], wantHeader) } }
	if string(got[len(wantHeader):]) != string(payload) { t.Fatal("payload was not preserved") }
}

func TestBuildUDPReplyIPv6(t *testing.T) {
	payload := []byte("v6")
	got, err := buildUDPReply(&net.UDPAddr{IP: net.ParseIP("2001:db8::7"), Port: 443}, payload)
	if err != nil { t.Fatal(err) }
	if len(got) != 4+16+2+len(payload) { t.Fatalf("packet length = %d", len(got)) }
	if got[0] != 0 || got[1] != 0 || got[2] != 0 || got[3] != 4 { t.Fatalf("ATYP header = %v, want IPv6", got[:4]) }
	if !net.IP(got[4:20]).Equal(net.ParseIP("2001:db8::7")) { t.Fatalf("reply IP = %v", net.IP(got[4:20])) }
	if binary.BigEndian.Uint16(got[20:22]) != 443 { t.Fatalf("reply port = %d", binary.BigEndian.Uint16(got[20:22])) }
	if string(got[22:]) != string(payload) { t.Fatal("payload was not preserved") }
}

func TestBuildUDPReplyRejectsInvalidAddress(t *testing.T) {
	if _, err := buildUDPReply(nil, nil); err == nil { t.Fatal("expected invalid address error") }
}

func TestResolveUDPAddrMarkedLiteralIPv4(t *testing.T) {
	got, err := resolveUDPAddrMarked("192.0.2.25:5353")
	if err != nil { t.Fatal(err) }
	if !got.IP.Equal(net.IPv4(192, 0, 2, 25)) || got.Port != 5353 {
		t.Fatalf("resolved address = %v, want 192.0.2.25:5353", got)
	}
}

func TestResolveUDPAddrMarkedRejectsInvalidPort(t *testing.T) {
	if _, err := resolveUDPAddrMarked("192.0.2.25:70000"); err == nil {
		t.Fatal("expected invalid port error")
	}
}

func TestResolveUDPAddrMarkedRejectsMissingPort(t *testing.T) {
	if _, err := resolveUDPAddrMarked("192.0.2.25"); err == nil {
		t.Fatal("expected missing port error")
	}
}


func socks5Handshake(t *testing.T, conn net.Conn) {
	t.Helper()
	if _, err := conn.Write([]byte{5, 1, 0}); err != nil { t.Fatal(err) }
	reply := make([]byte, 2)
	if _, err := io.ReadFull(conn, reply); err != nil { t.Fatal(err) }
	if reply[0] != 5 || reply[1] != 0 { t.Fatalf("handshake reply = %v", reply) }
}

func TestSocks5ConnectRelaysTCPPayload(t *testing.T) {
	echo, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil { t.Fatal(err) }
	defer echo.Close()
	go func() {
		for {
			conn, err := echo.Accept()
			if err != nil { return }
			go func(c net.Conn) { defer c.Close(); _, _ = io.Copy(c, c) }(conn)
		}
	}()

	s := NewSocks5Server("127.0.0.1:0")
	s.dialTCPOverride = func(addr string) (net.Conn, error) { return net.Dial("tcp", addr) }
	if err := s.Start(); err != nil { t.Fatal(err) }
	defer s.Stop()
	client, err := net.Dial("tcp", s.ln.Addr().String())
	if err != nil { t.Fatal(err) }
	defer client.Close()
	_ = client.SetDeadline(time.Now().Add(3 * time.Second))
	socks5Handshake(t, client)
	host, portText, err := net.SplitHostPort(echo.Addr().String())
	if err != nil { t.Fatal(err) }
	port, err := strconv.Atoi(portText)
	if err != nil { t.Fatal(err) }
	ip := net.ParseIP(host).To4()
	req := []byte{5, 1, 0, 1, ip[0], ip[1], ip[2], ip[3], byte(port >> 8), byte(port)}
	if _, err := client.Write(req); err != nil { t.Fatal(err) }
	reply := make([]byte, 10)
	if _, err := io.ReadFull(client, reply); err != nil { t.Fatal(err) }
	if reply[1] != 0 { t.Fatalf("CONNECT failed: %v", reply) }
	payload := []byte("socks5-tcp-e2e")
	if _, err := client.Write(payload); err != nil { t.Fatal(err) }
	got := make([]byte, len(payload))
	if _, err := io.ReadFull(client, got); err != nil { t.Fatal(err) }
	if string(got) != string(payload) { t.Fatalf("echo = %q, want %q", got, payload) }
}

func TestSocks5UDPAssociateRelaysDatagram(t *testing.T) {
	echo, err := net.ListenUDP("udp", &net.UDPAddr{IP: net.IPv4(127, 0, 0, 1)})
	if err != nil { t.Fatal(err) }
	defer echo.Close()
	go func() {
		buf := make([]byte, 2048)
		for {
			n, addr, err := echo.ReadFromUDP(buf)
			if err != nil { return }
			_, _ = echo.WriteToUDP(buf[:n], addr)
		}
	}()

	s := NewSocks5Server("127.0.0.1:0")
	s.dialUDPOverride = func() (*net.UDPConn, error) {
		return net.ListenUDP("udp", &net.UDPAddr{IP: net.IPv4zero, Port: 0})
	}
	if err := s.Start(); err != nil { t.Fatal(err) }
	defer s.Stop()
	control, err := net.Dial("tcp", s.ln.Addr().String())
	if err != nil { t.Fatal(err) }
	defer control.Close()
	_ = control.SetDeadline(time.Now().Add(4 * time.Second))
	socks5Handshake(t, control)
	if _, err := control.Write([]byte{5, 3, 0, 1, 0, 0, 0, 0, 0, 0}); err != nil { t.Fatal(err) }
	reply := make([]byte, 10)
	if _, err := io.ReadFull(control, reply); err != nil { t.Fatal(err) }
	if reply[1] != 0 { t.Fatalf("UDP ASSOCIATE failed: %v", reply) }
	relayIP := net.IP(reply[4:8])
	relayPort := int(binary.BigEndian.Uint16(reply[8:10]))
	if relayIP.IsUnspecified() { relayIP = net.IPv4(127, 0, 0, 1) }
	relay, err := net.DialUDP("udp", nil, &net.UDPAddr{IP: relayIP, Port: relayPort})
	if err != nil { t.Fatal(err) }
	defer relay.Close()
	_ = relay.SetDeadline(time.Now().Add(4 * time.Second))
	dst := echo.LocalAddr().(*net.UDPAddr)
	packet := []byte{0, 0, 0, 1, 127, 0, 0, 1, byte(dst.Port >> 8), byte(dst.Port)}
	packet = append(packet, []byte("socks5-udp-e2e")...)
	if _, err := relay.Write(packet); err != nil { t.Fatal(err) }
	got := make([]byte, 2048)
	n, err := relay.Read(got)
	if err != nil { t.Fatal(err) }
	if n < 10 || got[0] != 0 || got[1] != 0 || got[2] != 0 || got[3] != 1 {
		t.Fatalf("invalid UDP relay response: %v", got[:n])
	}
	if string(got[10:n]) != "socks5-udp-e2e" { t.Fatalf("UDP payload = %q", got[10:n]) }
}
