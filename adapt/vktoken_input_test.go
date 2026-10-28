package libs

import (
	"encoding/base64"
	"encoding/json"
	"os"
	"strings"
	"testing"
)

func TestSaveVKTokenInputAcceptsRawTokenAndOAuthRedirect(t *testing.T) {
	const raw = "vk1.a.fixture-token-value-that-is-long-enough"
	tests := []struct { name, input string }{
		{name: "raw token", input: raw},
		{name: "oauth fragment", input: "https://oauth.vk.com/blank.html#access_token=" + raw + "&expires_in=86400&user_id=1"},
		{name: "oauth query", input: "https://oauth.vk.ru/blank.html?access_token=" + raw + "&expires_in=86400"},
		{name: "query fragment parameters", input: "access_token=" + raw + "&expires_in=86400"},
		{name: "hash fragment parameters", input: "#access_token=" + raw + "&expires_in=86400"},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			core := &AppCore{appDir: t.TempDir()}
			if err := core.SaveVKTokenInput(tt.input); err != nil { t.Fatalf("SaveVKTokenInput rejected valid fixture: %v", err) }
			data, err := os.ReadFile(core.vkTokenFile())
			if err != nil { t.Fatalf("token file was not written: %v", err) }
			var got VKTokenJSON
			if err := json.Unmarshal(data, &got); err != nil { t.Fatalf("invalid token JSON: %v", err) }
			if got.Token != raw { t.Fatalf("saved token = %q, want fixture token", got.Token) }
			info, err := os.Stat(core.vkTokenFile())
			if err != nil { t.Fatal(err) }
			if info.Mode().Perm() != 0600 { t.Fatalf("token file permissions = %04o, want 0600", info.Mode().Perm()) }
		})
	}
}

func TestSaveVKTokenInputRejectsUntrustedRedirectsAndSilentToken(t *testing.T) {
	const raw = "vk1.a.fixture-token-value-that-is-long-enough"
	tests := []struct { name, input string }{
		{name: "untrusted host", input: "https://evil.example/blank.html#access_token=" + raw},
		{name: "wrong redirect path", input: "https://oauth.vk.com/steal.html#access_token=" + raw},
		{name: "insecure scheme", input: "http://oauth.vk.com/blank.html#access_token=" + raw},
		{name: "nonstandard port", input: "https://oauth.vk.ru:444/blank.html#access_token=" + raw},
		{name: "userinfo spoof", input: "https://oauth.vk.com@evil.example/blank.html#access_token=" + raw},
		{name: "silent token only", input: "https://oauth.vk.com/blank.html#silent_token=" + raw},
		{name: "silent token parameters only", input: "silent_token=" + raw},
		{name: "missing access token", input: "https://oauth.vk.com/blank.html#expires_in=86400"},
		{name: "malformed fragment", input: "https://oauth.vk.com/blank.html#access_token=%zz"},
		{name: "short raw token", input: "short"},
		{name: "whitespace in token", input: "vk1.a.fixture token value that should not be accepted"},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			core := &AppCore{appDir: t.TempDir()}
			if err := core.SaveVKTokenInput(tt.input); err == nil { t.Fatal("SaveVKTokenInput unexpectedly accepted invalid input") }
			if _, err := os.Stat(core.vkTokenFile()); !os.IsNotExist(err) { t.Fatalf("rejected input left a token file behind (stat err=%v)", err) }
		})
	}
}

func TestSaveVKTokenInputDoesNotExposeTokenInErrors(t *testing.T) {
	core := &AppCore{appDir: t.TempDir()}
	const secret = "vk1.a.fixture-token-value-that-is-long-enough"
	err := core.SaveVKTokenInput("https://evil.example/blank.html#access_token=" + secret)
	if err == nil { t.Fatal("expected untrusted redirect rejection") }
	if strings.Contains(err.Error(), secret) { t.Fatal("error message exposed token input") }
}

// Regression: verify the exact file written by the import/fallback path is the
// same appDir/token.json consumed by the original backend and exposed in state.
// This is deliberately offline and never contacts VK or uses a real credential.
func TestSavedVKTokenIsVisibleToBackendState(t *testing.T) {
	core := &AppCore{appDir: t.TempDir()}
	const fixture = "vk1.a.fixture-token-value-that-is-long-enough"
	if err := core.SaveVKTokenInput(fixture); err != nil { t.Fatalf("save fixture token: %v", err) }
	if got := core.ReadTokenFromFile(); got != fixture { t.Fatalf("ReadTokenFromFile() = %q, want fixture token", got) }
	if !core.HasVKToken() { t.Fatal("HasVKToken() false after successful save") }
}


func TestAutoVkBootstrapIsScopedToAutoVkMode(t *testing.T) {
	const token = "vk1.a.fixture-auto-vk-token-value"
	for _, mode := range []string{"manual", "autoApi", "autoVk"} {
		t.Run(mode, func(t *testing.T) {
			core := &AppCore{appDir: t.TempDir()}
			if !core.SaveSettings(\`{"authMode":"\` + mode + \`"}\`) {
				t.Fatal("could not persist hash acquisition mode")
			}
			if err := core.SaveVKTokenInput(token); err != nil {
				t.Fatalf("could not write VK token fixture: %v", err)
			}
			bridge := &Bridge{Core: core}
			got := bridge.AutoVkBootstrap()
			if mode != "autoVk" {
				if got != "" {
					t.Fatalf("%s unexpectedly emitted VK JS bootstrap: %q", mode, got)
				}
				return
			}
			if !strings.HasPrefix(got, "VK_JS_BOOTSTRAP:") || !strings.HasSuffix(got, "\n") {
				t.Fatalf("Auto VK bootstrap has invalid framing: %q", got)
			}
			encoded := strings.TrimSuffix(strings.TrimPrefix(got, "VK_JS_BOOTSTRAP:"), "\n")
			decoded, err := base64.StdEncoding.DecodeString(encoded)
			if err != nil {
				t.Fatalf("decode bootstrap: %v", err)
			}
			var payload map[string]string
			if err := json.Unmarshal(decoded, &payload); err != nil {
				t.Fatalf("decode payload: %v", err)
			}
			if payload["token"] != token {
				t.Fatalf("bootstrap token = %q, want fixture token", payload["token"])
			}
		})
	}
}
