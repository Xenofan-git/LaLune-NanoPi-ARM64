//go:build linux

package main

import (
	"net/http/httptest"
	"testing"
	"time"

	libs "lalune-desktop/Libs"
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

func TestSelectedConfigJsonClearsEmptySelection(t *testing.T) {
	core := &libs.AppCore{}
	if !core.SetSelectedConfigJson(`{"id":7,"name":"test"}`) {
		t.Fatal("could not set selected config")
	}
	if core.GetSelectedConfig() == nil {
		t.Fatal("selected config unexpectedly nil")
	}
	for _, raw := range []string{"null", "{}", ""} {
		if !core.SetSelectedConfigJson(raw) {
			t.Fatalf("could not clear selection with %q", raw)
		}
		if core.GetSelectedConfig() != nil {
			t.Fatalf("selection was not cleared for %q", raw)
		}
	}
}


func TestCaptchaRequestIsActive(t *testing.T) {
	now := time.Unix(1791549509, 0)
	tests := []struct {
		name string
		mode string
		url  string
		want bool
	}{
		{name: "active manual challenge", mode: "manual", url: "https://id.vk.ru/not_robot_captcha?expired_at=1791549600", want: true},
		{name: "automatic event never opens dialog", mode: "auto", url: "https://id.vk.ru/not_robot_captcha?expired_at=1791549600", want: false},
		{name: "expired manual challenge", mode: "manual", url: "https://id.vk.ru/not_robot_captcha?expired_at=1791549400", want: false},
		{name: "missing expiry", mode: "manual", url: "https://id.vk.ru/not_robot_captcha", want: false},
		{name: "invalid expiry", mode: "manual", url: "https://id.vk.ru/not_robot_captcha?expired_at=nope", want: false},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			if got := captchaRequestIsActive(tt.mode, tt.url, now); got != tt.want {
				t.Fatalf("captchaRequestIsActive() = %v, want %v", got, tt.want)
			}
		})
	}
}

func TestDirectDomainValidation(t *testing.T) {
	tests := []struct {
		name string
		domain string
		want bool
	}{
		{name: "base domain", domain: "example.com", want: true},
		{name: "subdomain", domain: "api.example.com", want: true},
		{name: "reject wildcard syntax", domain: "*.example.com", want: false},
		{name: "reject URL", domain: "https://example.com", want: false},
		{name: "reject path", domain: "example.com/path", want: false},
		{name: "reject empty label", domain: "example..com", want: false},
		{name: "reject leading hyphen", domain: "-bad.example", want: false},
		{name: "reject blank", domain: "", want: false},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			if got := validDirectDomain(tt.domain); got != tt.want {
				t.Fatalf("validDirectDomain(%q) = %v, want %v", tt.domain, got, tt.want)
			}
		})
	}
}

func TestNormalizeDirectIPs(t *testing.T) {
	got, err := normalizeDirectIPs("192.0.2.1\n192.0.2.0/24")
	if err != nil {
		t.Fatalf("normalizeDirectIPs(valid values): %v", err)
	}
	if len(got) != 2 || got[0] != "192.0.2.1" || got[1] != "192.0.2.0/24" {
		t.Fatalf("unexpected normalized IPs: %#v", got)
	}
	if _, err := normalizeDirectIPs("2001:db8::1"); err == nil {
		t.Fatal("expected IPv6 to be rejected while Direct supports IPv4 only")
	}
	if _, err := normalizeDirectIPs("192.0.2.999"); err == nil {
		t.Fatal("expected malformed IPv4 to be rejected")
	}
	if _, err := normalizeDirectIPs("0.0.0.0/0"); err == nil {
		t.Fatal("expected default route CIDR to be rejected for Direct")
	}
}
