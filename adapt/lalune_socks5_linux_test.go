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
