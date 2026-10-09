//go:build linux

package main

import (
	"net/http/httptest"
	"testing"
)

func TestPrivateClient(t *testing.T) {
	tests := []struct {
		name       string
		remoteAddr string
		xRealIP    string
		want       bool
	}{
		{name: "LAN IPv4", remoteAddr: "192.168.4.12:43120", want: true},
		{name: "loopback", remoteAddr: "127.0.0.1:43120", want: true},
		{name: "Tailscale peer", remoteAddr: "127.0.0.1:43120", xRealIP: "100.70.73.57", want: true},
		{name: "Tailscale IPv6", remoteAddr: "127.0.0.1:43120", xRealIP: "fd7a:115c:a1e0::1234", want: true},
		{name: "public peer", remoteAddr: "8.8.8.8:43120", want: false},
		{name: "public proxy client overrides loopback", remoteAddr: "127.0.0.1:43120", xRealIP: "8.8.8.8", want: false},
		{name: "malformed proxy client", remoteAddr: "127.0.0.1:43120", xRealIP: "not-an-ip", want: false},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			r := httptest.NewRequest("POST", "http://localhost/deploy", nil)
			r.RemoteAddr = tt.remoteAddr
			if tt.xRealIP != "" {
				r.Header.Set("X-Real-IP", tt.xRealIP)
			}
			if got := privateClient(r); got != tt.want {
				t.Fatalf("privateClient() = %v, want %v", got, tt.want)
			}
		})
	}
}
