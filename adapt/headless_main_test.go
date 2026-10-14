//go:build linux

package main

import (
	"encoding/json"
	"io"
	"net/http/httptest"
	"slices"
	"strings"
	"testing"
	"time"

	libs "lalune-desktop/Libs"
)

func TestAutoApiCallCountAndHashBatchContract(t *testing.T) {
	cases := []struct {
		name string
		workers int
		perCall int
		want int
	}{
		{name: "one worker group", workers: 1, perCall: 9, want: 1},
		{name: "exactly one call", workers: 9, perCall: 9, want: 1},
		{name: "rounds up partial call", workers: 10, perCall: 9, want: 2},
		{name: "three calls for 27 workers", workers: 27, perCall: 9, want: 3},
		{name: "caps at six calls", workers: 126, perCall: 9, want: 6},
		{name: "caps pathological worker count", workers: 10000, perCall: 1, want: 6},
	}
	for _, tt := range cases {
		t.Run(tt.name, func(t *testing.T) {
			if got := libs.CallCountForWorkers(tt.workers, tt.perCall); got != tt.want {
				t.Fatalf("CallCountForWorkers(%d, %d) = %d, want %d", tt.workers, tt.perCall, got, tt.want)
			}
		})
	}

	batch := &libs.VkCallsBatch{Calls: []libs.VkAutoCall{
		{CallID: "fixture-call-1", Hash: "fixture-hash-1"},
		{CallID: "fixture-call-2", Hash: "fixture-hash-2"},
	}}
	if got, want := batch.Hashes(), []string{"fixture-hash-1", "fixture-hash-2"}; !slices.Equal(got, want) {
		t.Fatalf("Auto API hashes = %#v, want %#v", got, want)
	}
	if got, want := batch.CallIds(), []string{"fixture-call-1", "fixture-call-2"}; !slices.Equal(got, want) {
		t.Fatalf("Auto API call IDs = %#v, want %#v", got, want)
	}
}

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
		{name: "active manual fallback", mode: "manual", url: "https://id.vk.ru/not_robot_captcha?expired_at=1791549600", want: true},
		{name: "explicit WBV selected mode uses Linux browser bridge", mode: "selected", url: "https://id.vk.ru/not_robot_captcha?expired_at=1791549600", want: true},
		{name: "selected mode is case and whitespace tolerant", mode: " Selected ", url: "https://id.vk.ru/not_robot_captcha?expired_at=1791549600", want: true},
		{name: "automatic retry never opens dialog", mode: "auto", url: "https://id.vk.ru/not_robot_captcha?expired_at=1791549600", want: false},
		{name: "unknown mode never opens dialog", mode: "wv", url: "https://id.vk.ru/not_robot_captcha?expired_at=1791549600", want: false},
		{name: "expired manual challenge", mode: "manual", url: "https://id.vk.ru/not_robot_captcha?expired_at=1791549400", want: false},
		{name: "expired selected challenge", mode: "selected", url: "https://id.vk.ru/not_robot_captcha?expired_at=1791549400", want: false},
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

func TestRJSManualFallbackSupersedesAutoCaptchaEvent(t *testing.T) {
    // Simulate the core's event stream after RJS fails: its earlier Auto retry
    // must not open the Linux overlay, but the later manual fallback must.
    old := struct {
        pending bool
        mode, uri, session, handled string
        updated time.Time
    }{}
    captchaMu.Lock()
    old.pending, old.mode, old.uri, old.session, old.handled, old.updated =
        captchaPending, captchaMode, captchaRedirectURI, captchaSessionToken, captchaHandledSession, captchaUpdated
    captchaPending, captchaMode, captchaRedirectURI, captchaSessionToken, captchaHandledSession = false, "", "", "", ""
    captchaUpdated = time.Time{}
    captchaMu.Unlock()
    t.Cleanup(func() {
        captchaMu.Lock()
        captchaPending, captchaMode, captchaRedirectURI, captchaSessionToken, captchaHandledSession, captchaUpdated =
            old.pending, old.mode, old.uri, old.session, old.handled, old.updated
        captchaMu.Unlock()
    })

    now := time.Unix(1791549509, 0)
    uri := "https://id.vk.ru/not_robot_captcha?expired_at=1791549600"
    autoLogs, _ := json.Marshal([]string{"CAPTCHA_SOLVE|auto|" + uri + "|rjs-auto-session"})
    refreshCaptchaStateFromLogs(string(autoLogs), now)
    captchaMu.Lock()
    if captchaPending || captchaMode != "" {
        t.Fatalf("auto retry unexpectedly opened manual overlay: pending=%v mode=%q", captchaPending, captchaMode)
    }
    captchaMu.Unlock()

    fallbackLogs, _ := json.Marshal([]string{
        "CAPTCHA_SOLVE|auto|" + uri + "|rjs-auto-session",
        "CAPTCHA_SOLVE|manual|" + uri + "|rjs-manual-session",
    })
    refreshCaptchaStateFromLogs(string(fallbackLogs), now.Add(time.Second))
    captchaMu.Lock()
    defer captchaMu.Unlock()
    if !captchaPending {
        t.Fatal("manual RJS fallback did not create a pending CAPTCHA")
    }
    if captchaMode != "manual" {
        t.Fatalf("fallback mode = %q, want manual", captchaMode)
    }
    if captchaSessionToken != "rjs-manual-session" {
        t.Fatalf("fallback session = %q, want rjs-manual-session", captchaSessionToken)
    }
    if captchaRedirectURI != uri {
        t.Fatalf("fallback redirect URI = %q, want %q", captchaRedirectURI, uri)
    }
    if !captchaUpdated.Equal(now.Add(time.Second)) {
        t.Fatalf("updated = %v, want %v", captchaUpdated, now.Add(time.Second))
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


func TestVersionEndpointReportsBuildProvenance(t *testing.T) {
	old := []string{buildCommit, buildRunID, buildRunNumber, buildDate, buildBranch, buildUpstreamCommit}
	buildCommit, buildRunID, buildRunNumber, buildDate = "commit-test", "run-test", "42", "2026-10-09T00:00:00Z"
	buildBranch, buildUpstreamCommit = "feature/csqtt-direct-route-tab", "e4a6d08b63aef6025bf8ad8f77da660ea552e04b"
	defer func() {
		buildCommit, buildRunID, buildRunNumber, buildDate = old[0], old[1], old[2], old[3]
		buildBranch, buildUpstreamCommit = old[4], old[5]
	}()
	r := httptest.NewRequest("GET", "/version", nil)
	w := httptest.NewRecorder()
	apiHandler(nil).ServeHTTP(w, r)
	if w.Code != 200 { t.Fatalf("/version status = %d, want 200", w.Code) }
	var got map[string]any
	if err := json.Unmarshal(w.Body.Bytes(), &got); err != nil { t.Fatalf("invalid /version JSON: %v", err) }
	want := map[string]string{
		"backend": "original-go", "core": "csqtt-server/2.1.9", "ui": "0.6.0",
		"commit": "commit-test", "buildRun": "run-test", "buildNumber": "42",
		"buildDate": "2026-10-09T00:00:00Z", "buildBranch": "feature/csqtt-direct-route-tab",
		"upstreamCommit": "e4a6d08b63aef6025bf8ad8f77da660ea552e04b",
	}
	for key, wantValue := range want {
		if got[key] != wantValue { t.Errorf("/version[%q] = %#v, want %q", key, got[key], wantValue) }
	}
}

func TestDirectPlanTransitions(t *testing.T) {
	tests := []struct {
		name, domains, ips string
		wantDomains, wantIPs []string
		wantDNS, wantEnabled bool
		wantErr bool
	}{
		{name: "domains and IPs", domains: "example.com, api.example.com", ips: "192.0.2.1,192.0.2.0/24", wantDomains: []string{"example.com", "api.example.com"}, wantIPs: []string{"192.0.2.1", "192.0.2.0/24"}, wantDNS: true, wantEnabled: true},
		{name: "IP only after domains", ips: "192.0.2.1", wantIPs: []string{"192.0.2.1"}, wantEnabled: true},
		{name: "domains only after IPs", domains: "example.com", wantDomains: []string{"example.com"}, wantDNS: true, wantEnabled: true},
		{name: "empty after domains and IPs", wantEnabled: false},
		{name: "reject bad domain without plan", domains: "https://example.com", wantErr: true},
		{name: "reject bad IP without plan", ips: "192.0.2.999", wantErr: true},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			domains, ips, needsDNS, err := prepareDirectPlan(tt.domains, tt.ips)
			if (err != nil) != tt.wantErr { t.Fatalf("prepareDirectPlan error = %v, wantErr %v", err, tt.wantErr) }
			if tt.wantErr { return }
			if !slices.Equal(domains, tt.wantDomains) { t.Errorf("domains = %#v, want %#v", domains, tt.wantDomains) }
			if !slices.Equal(ips, tt.wantIPs) { t.Errorf("ips = %#v, want %#v", ips, tt.wantIPs) }
			if needsDNS != tt.wantDNS { t.Errorf("needsDNS = %v, want %v", needsDNS, tt.wantDNS) }
			if (len(domains)+len(ips) > 0) != tt.wantEnabled { t.Errorf("enabled = %v, want %v", len(domains)+len(ips)>0, tt.wantEnabled) }
		})
	}
}


// setCaptchaTestState installs an isolated pending challenge for endpoint tests.
func setCaptchaTestState(t *testing.T, session string) {
	t.Helper()
	captchaMu.Lock()
	oldPending, oldMode := captchaPending, captchaMode
	oldURI, oldSession, oldHandled, oldUpdated := captchaRedirectURI, captchaSessionToken, captchaHandledSession, captchaUpdated
	captchaPending = true
	captchaMode = "manual"
	captchaRedirectURI = "https://id.vk.ru/not_robot_captcha?expired_at=1791549600"
	captchaSessionToken = session
	captchaHandledSession = ""
	captchaUpdated = time.Now()
	captchaMu.Unlock()
	t.Cleanup(func() {
		captchaMu.Lock()
		captchaPending, captchaMode = oldPending, oldMode
		captchaRedirectURI, captchaSessionToken = oldURI, oldSession
		captchaHandledSession, captchaUpdated = oldHandled, oldUpdated
		captchaMu.Unlock()
	})
}

func TestCaptchaResultEndpointForwardsToCoreStdin(t *testing.T) {
	const session = "ci-captcha-session"
	const result = "fixture-captcha-result"
	setCaptchaTestState(t, session)

	reader, writer := io.Pipe()
	defer reader.Close()
	defer writer.Close()
	app := &App{runner: &LinuxRunner{}}
	linuxRunnerInputs.Store(app.runner, writer)
	defer linuxRunnerInputs.Delete(app.runner)

	expected := "CAPTCHA_RESULT|" + result + "\n"
	readResult := make(chan string, 1)
	readErr := make(chan error, 1)
	go func() {
		buf := make([]byte, len(expected))
		_, err := io.ReadFull(reader, buf)
		if err != nil {
			readErr <- err
			return
		}
		readResult <- string(buf)
	}()

	body := strings.NewReader(`{"sessionToken":"ci-captcha-session","result":"fixture-captcha-result"}`)
	req := httptest.NewRequest("POST", "/captcha/result", body)
	rec := httptest.NewRecorder()
	apiHandler(app).ServeHTTP(rec, req)
	if rec.Code != 200 {
		t.Fatalf("/captcha/result status = %d, want 200: %s", rec.Code, rec.Body.String())
	}
	var response map[string]bool
	if err := json.Unmarshal(rec.Body.Bytes(), &response); err != nil {
		t.Fatalf("invalid /captcha/result JSON: %v", err)
	}
	if !response["ok"] {
		t.Fatalf("/captcha/result rejected valid fixture: %s", rec.Body.String())
	}
	select {
	case got := <-readResult:
		if got != expected {
			t.Fatalf("core stdin = %q, want %q", got, expected)
		}
	case err := <-readErr:
		t.Fatalf("reading core stdin fixture: %v", err)
	case <-time.After(time.Second):
		t.Fatal("CAPTCHA_RESULT was not forwarded to core stdin")
	}
}

func TestCaptchaResultEndpointRejectsStaleSessionAndUnsafeResult(t *testing.T) {
	const session = "ci-captcha-session"
	setCaptchaTestState(t, session)
	app := &App{runner: &LinuxRunner{}}

	tests := []struct {
		name string
		body string
	}{
		{name: "stale session", body: `{"sessionToken":"old-session","result":"fixture-result"}`},
		{name: "embedded newline", body: `{"sessionToken":"ci-captcha-session","result":"fixture\nresult"}`},
		{name: "empty result", body: `{"sessionToken":"ci-captcha-session","result":"  "}`},
		{name: "oversized result", body: `{"sessionToken":"ci-captcha-session","result":"` + strings.Repeat("x", 16385) + `"}`},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			req := httptest.NewRequest("POST", "/captcha/result", strings.NewReader(tt.body))
			rec := httptest.NewRecorder()
			apiHandler(app).ServeHTTP(rec, req)
			if rec.Code != 200 {
				t.Fatalf("/captcha/result status = %d, want 200: %s", rec.Code, rec.Body.String())
			}
			var response map[string]bool
			if err := json.Unmarshal(rec.Body.Bytes(), &response); err != nil {
				t.Fatalf("invalid /captcha/result JSON: %v", err)
			}
			if response["ok"] {
				t.Fatalf("/captcha/result accepted unsafe fixture: %s", tt.name)
			}
		})
	}
}

func TestCaptchaResultEndpointRequiresPost(t *testing.T) {
	req := httptest.NewRequest("GET", "/captcha/result", nil)
	rec := httptest.NewRecorder()
	apiHandler(&App{}).ServeHTTP(rec, req)
	if rec.Code != 405 {
		t.Fatalf("GET /captcha/result status = %d, want 405", rec.Code)
	}
	if got := rec.Header().Get("Allow"); got != "POST" {
		t.Fatalf("GET /captcha/result Allow = %q, want POST", got)
	}
}


func TestCaptchaResultEndpointRejectsMalformedJSON(t *testing.T) {
	setCaptchaTestState(t, "ci-captcha-session")
	req := httptest.NewRequest("POST", "/captcha/result", strings.NewReader(`{"sessionToken":`))
	rec := httptest.NewRecorder()
	apiHandler(&App{runner: &LinuxRunner{}}).ServeHTTP(rec, req)
	if rec.Code != 400 {
		t.Fatalf("malformed POST /captcha/result status = %d, want 400", rec.Code)
	}
}

func TestCaptchaCancelEndpointForwardsCancellationAndConsumesChallenge(t *testing.T) {
	const session = "ci-captcha-cancel-session"
	setCaptchaTestState(t, session)

	reader, writer := io.Pipe()
	defer reader.Close()
	defer writer.Close()
	app := &App{runner: &LinuxRunner{}}
	linuxRunnerInputs.Store(app.runner, writer)
	defer linuxRunnerInputs.Delete(app.runner)

	expected := "CAPTCHA_RESULT|error:cancelled\n"
	gotCh := make(chan string, 1)
	errCh := make(chan error, 1)
	go func() {
		buf := make([]byte, len(expected))
		_, err := io.ReadFull(reader, buf)
		if err != nil {
			errCh <- err
			return
		}
		gotCh <- string(buf)
	}()

	req := httptest.NewRequest("POST", "/captcha/cancel", nil)
	rec := httptest.NewRecorder()
	apiHandler(app).ServeHTTP(rec, req)
	if rec.Code != 200 {
		t.Fatalf("POST /captcha/cancel status = %d, want 200: %s", rec.Code, rec.Body.String())
	}
	var response map[string]bool
	if err := json.Unmarshal(rec.Body.Bytes(), &response); err != nil {
		t.Fatalf("invalid /captcha/cancel JSON: %v", err)
	}
	if !response["ok"] {
		t.Fatalf("/captcha/cancel rejected active fixture: %s", rec.Body.String())
	}
	select {
	case got := <-gotCh:
		if got != expected {
			t.Fatalf("core stdin = %q, want %q", got, expected)
		}
	case err := <-errCh:
		t.Fatalf("reading cancellation from core stdin: %v", err)
	case <-time.After(time.Second):
		t.Fatal("cancellation was not forwarded to core stdin")
	}

	captchaMu.Lock()
	pending, activeSession := captchaPending, captchaSessionToken
	captchaMu.Unlock()
	if pending || activeSession != "" {
		t.Fatalf("challenge was not consumed after cancellation: pending=%v session=%q", pending, activeSession)
	}
}

func TestCaptchaStateEndpointRequiresGet(t *testing.T) {
	req := httptest.NewRequest("POST", "/captcha/state", nil)
	rec := httptest.NewRecorder()
	apiHandler(&App{}).ServeHTTP(rec, req)
	if rec.Code != 405 {
		t.Fatalf("POST /captcha/state status = %d, want 405", rec.Code)
	}
	if got := rec.Header().Get("Allow"); got != "GET" {
		t.Fatalf("POST /captcha/state Allow = %q, want GET", got)
	}
}
