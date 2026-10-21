//go:build linux

package main

import (
	"encoding/binary"
	"io"
	"net"
	"testing"
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
