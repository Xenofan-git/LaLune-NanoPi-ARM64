package libs

import (
	"encoding/json"
	"os"
	"strings"
	"testing"
)

func TestSaveVKTokenInputAcceptsRawTokenAndOAuthRedirect(t *testing.T) {
	const raw = "vk1.a.fixture-token-value-that-is-long-enough"
	tests := []struct {
		name, input string
	}{
		{name: "raw token", input: raw},
		{name: "oauth fragment", input: "https://oauth.vk.com/blank.html#access_token=" + raw + "&expires_in=86400&user_id=1"},
		{name: "oauth query", input: "https://oauth.vk.ru/blank.html?access_token=" + raw + "&expires_in=86400"},
		{name: "query fragment parameters", input: "access_token=" + raw + "&expires_in=86400"},
		{name: "hash fragment parameters", input: "#access_token=" + raw + "&expires_in=86400"},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			core := &AppCore{appDir: t.TempDir()}
			if err := core.SaveVKTokenInput(tt.input); err != nil {
				t.Fatalf("SaveVKTokenInput rejected valid fixture: %v", err)
			}
			data, err := os.ReadFile(core.vkTokenFile())
			if err != nil {
				t.Fatalf("token file was not written: %v", err)
			}
			var got VKTokenJSON
			if err := json.Unmarshal(data, &got); err != nil {
				t.Fatalf("invalid token JSON: %v", err)
			}
			if got.Token != raw {
				t.Fatalf("saved token = %q, want fixture token", got.Token)
			}
			info, err := os.Stat(core.vkTokenFile())
			if err != nil {
				t.Fatal(err)
			}
			if info.Mode().Perm() != 0600 {
				t.Fatalf("token file permissions = %04o, want 0600", info.Mode().Perm())
			}
		})
	}
}

func TestSaveVKTokenInputRejectsUntrustedRedirectsAndSilentToken(t *testing.T) {
	const raw = "vk1.a.fixture-token-value-that-is-long-enough"
	tests := []struct {
		name, input string
	}{
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
			if err := core.SaveVKTokenInput(tt.input); err == nil {
				t.Fatal("SaveVKTokenInput unexpectedly accepted invalid input")
			}
			if _, err := os.Stat(core.vkTokenFile()); !os.IsNotExist(err) {
				t.Fatalf("rejected input left a token file behind (stat err=%v)", err)
			}
		})
	}
}

func TestSaveVKTokenInputDoesNotExposeTokenInErrors(t *testing.T) {
	core := &AppCore{appDir: t.TempDir()}
	const secret = "vk1.a.fixture-token-value-that-is-long-enough"
	err := core.SaveVKTokenInput("https://evil.example/blank.html#access_token=" + secret)
	if err == nil {
		t.Fatal("expected untrusted redirect rejection")
	}
	if strings.Contains(err.Error(), secret) {
		t.Fatal("error message exposed token input")
	}
}
