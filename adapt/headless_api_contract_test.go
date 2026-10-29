//go:build linux

package main

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

// These tests exercise the actual registered HTTP handlers without starting
// LaLune, changing routes, or invoking network-dependent operations.
func TestAPIReadOnlyEndpointsReturnValidJSON(t *testing.T) {
	for _, path := range []string{"/ping", "/version", "/socks5/status"} {
		t.Run(path, func(t *testing.T) {
			req := httptest.NewRequest(http.MethodGet, path, nil)
			rec := httptest.NewRecorder()
			apiHandler(&App{}).ServeHTTP(rec, req)
			if rec.Code != http.StatusOK {
				t.Fatalf("GET %s status=%d body=%q", path, rec.Code, rec.Body.String())
			}
			var payload map[string]any
			if err := json.Unmarshal(rec.Body.Bytes(), &payload); err != nil {
				t.Fatalf("GET %s returned invalid JSON: %v", path, err)
			}
			if path == "/ping" && payload["ok"] != true {
				t.Fatalf("GET /ping payload=%v", payload)
			}
			if path == "/version" {
				for _, key := range []string{"api", "backend", "core", "ui", "commit", "buildRun", "buildNumber", "buildDate", "buildBranch", "upstreamCommit"} {
					if _, ok := payload[key]; !ok {
						t.Errorf("GET /version missing %q field: %v", key, payload)
					}
				}
			}
		})
	}
}

func TestAPIHandlersRejectWrongMethods(t *testing.T) {
	cases := []struct{ path, method, wantAllow string }{
		{"/ping", http.MethodPost, http.MethodGet},
		{"/version", http.MethodPost, http.MethodGet},
		{"/vpn/status", http.MethodPost, http.MethodGet},
		{"/vpn/connect", http.MethodGet, http.MethodPost},
		{"/vpn/disconnect", http.MethodGet, http.MethodPost},
		{"/logs", http.MethodPost, http.MethodGet},
		{"/logs/clear", http.MethodGet, http.MethodPost},
		{"/deploy/status", http.MethodPost, http.MethodGet},
		{"/deploy/log", http.MethodPost, http.MethodGet},
		{"/updates/core/check", http.MethodPost, http.MethodGet},
		{"/updates/core/wait", http.MethodGet, http.MethodPost},
		{"/updates/lalune", http.MethodPost, http.MethodGet},
		{"/vk/state", http.MethodPost, http.MethodGet},
		{"/vk/login", http.MethodGet, http.MethodPost},
		{"/vk/validate", http.MethodPost, http.MethodGet},
		{"/vk/auto", http.MethodGet, http.MethodPost},
		{"/vk/auto/poll", http.MethodPost, http.MethodGet},
		{"/vk/finish", http.MethodGet, http.MethodPost},
		{"/captcha/state", http.MethodPost, http.MethodGet},
		{"/captcha/result", http.MethodGet, http.MethodPost},
		{"/captcha/cancel", http.MethodGet, http.MethodPost},
	}
	for _, tc := range cases {
		t.Run(tc.path+"_"+tc.method, func(t *testing.T) {
			req := httptest.NewRequest(tc.method, tc.path, nil)
			req.RemoteAddr = "192.168.1.2:12345"
			rec := httptest.NewRecorder()
			apiHandler(&App{}).ServeHTTP(rec, req)
			if rec.Code != http.StatusMethodNotAllowed {
				t.Fatalf("%s %s status=%d body=%q, want 405", tc.method, tc.path, rec.Code, rec.Body.String())
			}
			if got := rec.Header().Get("Allow"); !strings.Contains(got, tc.wantAllow) {
				t.Errorf("%s %s Allow=%q, want to contain %q", tc.method, tc.path, got, tc.wantAllow)
			}
		})
	}
}

func TestAPIJSONEndpointsRejectMalformedPayloads(t *testing.T) {
	cases := []struct{ path, method string }{
		{"/configs", http.MethodPost},
		{"/configs/selected", http.MethodPut},
		{"/settings", http.MethodPut},
		{"/vpn/connect", http.MethodPost},
		{"/vk/finish", http.MethodPost},
		{"/captcha/result", http.MethodPost},
		{"/deploy", http.MethodPost},
	}
	for _, tc := range cases {
		t.Run(tc.path, func(t *testing.T) {
			req := httptest.NewRequest(tc.method, tc.path, strings.NewReader("{malformed"))
			req.RemoteAddr = "192.168.1.2:12345"
			req.Header.Set("Content-Type", "application/json")
			rec := httptest.NewRecorder()
			apiHandler(&App{}).ServeHTTP(rec, req)
			if rec.Code != http.StatusBadRequest {
				t.Fatalf("%s %s status=%d body=%q, want 400", tc.method, tc.path, rec.Code, rec.Body.String())
			}
		})
	}
}

func TestSensitiveEndpointsDenyPublicPeers(t *testing.T) {
	cases := []struct{ path, method, body string }{
		{"/deploy", http.MethodPost, `{}`},
		{"/deploy/status", http.MethodGet, ""},
		{"/deploy/log", http.MethodGet, ""},
		{"/vk/import", http.MethodPost, `{"token":"fixture-token"}`},
	}
	for _, tc := range cases {
		t.Run(tc.path, func(t *testing.T) {
			req := httptest.NewRequest(tc.method, tc.path, strings.NewReader(tc.body))
			req.RemoteAddr = "203.0.113.7:12345"
			rec := httptest.NewRecorder()
			apiHandler(&App{}).ServeHTTP(rec, req)
			if rec.Code != http.StatusForbidden {
				t.Fatalf("%s %s status=%d body=%q, want 403", tc.method, tc.path, rec.Code, rec.Body.String())
			}
		})
	}
}
