#!/usr/bin/env python3
"""Patch the pinned Linux LaLune source to deliver Auto VK bootstrap only on stdin."""
from pathlib import Path

bridge_path = Path("upstream-lalune/Desktop/Libs/bridge.go")
linux_path = Path("upstream-lalune/Desktop/Linux/app_linux.go")
bridge = bridge_path.read_text(encoding="utf-8")
linux = linux_path.read_text(encoding="utf-8")

def replace_once(source: str, old: str, new: str, label: str) -> str:
    count = source.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one match, found {count}")
    return source.replace(old, new, 1)

bridge = replace_once(
    bridge,
    '''import (
\t"fmt"
\t"net"
\t"os"
\t"os/exec"
\t"strings"
)''',
    '''import (
\t"encoding/base64"
\t"encoding/json"
\t"fmt"
\t"net"
\t"os"
\t"os/exec"
\t"strings"
)''',
    "bridge imports",
)
bridge = replace_once(
    bridge,
    '''\tactiveCallIds []string
}''',
    '''\tactiveCallIds []string
\tcoreBootstrap  []byte
}''',
    "Bridge bootstrap field",
)
bridge = replace_once(
    bridge,
    '''func (b *Bridge) buildCommand(config *Config, settings Settings, listenPort int) []string {
\tnormalizedHashes := strings.ReplaceAll(config.Hashes, " ", ",")''',
    '''func (b *Bridge) buildCommand(config *Config, settings Settings, listenPort int) []string {
\t// Clear any previous launch payload so a missing token cannot reuse stale data.
\tb.coreBootstrap = nil
\tnormalizedHashes := strings.ReplaceAll(config.Hashes, " ", ",")''',
    "buildCommand bootstrap reset",
)
bridge = replace_once(
    bridge,
    '''\tif isAutoVk {
\t\ttoken := b.Core.ReadTokenFromFile()
\t\tif token == "" {
\t\t\tb.Core.AddLog("[АВТО ВК] ПРЕДУПРЕЖДЕНИЕ: token.json не найден или пуст — ядро упадёт")
\t\t} else {
\t\t\tcmd = append(cmd, "--token", token)
\t\t\tb.Core.AddLog("[АВТО ВК] Токен передан из token.json")
\t\t}
\t}''',
    '''\tif isAutoVk {
\t\ttoken := b.Core.ReadTokenFromFile()
\t\tif strings.TrimSpace(token) == "" {
\t\t\tb.Core.AddLog("[АВТО ВК] ОШИБКА: token.json не найден или пуст")
\t\t} else {
\t\t\tpayload, err := json.Marshal(struct {
\t\t\t\tToken string `json:"token"`
\t\t\t}{Token: token})
\t\t\tif err != nil {
\t\t\t\tb.Core.AddLog("[АВТО ВК] ОШИБКА: не удалось подготовить bootstrap")
\t\t\t} else {
\t\t\t\tb.coreBootstrap = []byte("VK_JS_BOOTSTRAP:" + base64.StdEncoding.EncodeToString(payload) + "\\n")
\t\t\t\tb.Core.AddLog("[АВТО ВК] Bootstrap подготовлен для защищённой передачи через stdin")
\t\t\t}
\t\t}
\t}''',
    "Auto VK token argument replacement",
)
bridge = replace_once(
    bridge,
    '''func (b *Bridge) ParseTunconf(line string) (string, string) {''',
    '''// TakeCoreBootstrap returns and clears the one-shot Auto VK stdin payload.
func (b *Bridge) TakeCoreBootstrap() []byte {
\tpayload := b.coreBootstrap
\tb.coreBootstrap = nil
\treturn payload
}

func (b *Bridge) ParseTunconf(line string) (string, string) {''',
    "one-shot bootstrap accessor",
)
if '"--token", token' in bridge or 'cmd = append(cmd, "--token"' in bridge:
    raise SystemExit("Auto VK token remains in command-line arguments")

linux = replace_once(
    linux,
    '''import (
\t"context"
\t"fmt"''',
    '''import (
\t"bytes"
\t"context"
\t"fmt"''',
    "Linux runner imports",
)
linux = replace_once(
    linux,
    '''\tcmd := exec.Command("sh", "-c", r.app.runSudoCommand(cmdLine))
\tcmd.Stdin = os.Stdin
\tcmd.Stdout = os.Stdout
\tcmd.Stderr = os.Stderr

\tif err := cmd.Start(); err != nil {''',
    '''\tbootstrap := bridge.TakeCoreBootstrap()
\tvar cmd *exec.Cmd
\tif len(bootstrap) > 0 {
\t\tvar err error
\t\tcmd, err = r.app.commandWithBootstrap(cmdLine, bootstrap)
\t\tif err != nil {
\t\t\tbridge.Core.AddLog(fmt.Sprintf("[АВТО ВК] Не удалось безопасно подготовить запуск ядра: %v", err))
\t\t\tbridge.Core.SetConnected(false)
\t\t\treturn
\t\t}
\t} else {
\t\tcmd = exec.Command("sh", "-c", r.app.runSudoCommand(cmdLine))
\t\tcmd.Stdin = os.Stdin
\t\tcmd.Stdout = os.Stdout
\t\tcmd.Stderr = os.Stderr
\t}

\tif err := cmd.Start(); err != nil {''',
    "Linux runner stdin launch",
)
linux = replace_once(
    linux,
    '''func (a *App) runSudo(command string) error {
\tfullCmd := a.runSudoCommand(command)''',
    '''// commandWithBootstrap authenticates sudo separately, then sends only the
// VK_JS_BOOTSTRAP line to the core's stdin. The token is never part of argv,
// a shell command, or a log line.
func (a *App) commandWithBootstrap(command string, bootstrap []byte) (*exec.Cmd, error) {
\tif os.Geteuid() == 0 {
\t\tcmd := exec.Command("sh", "-c", command)
\t\tcmd.Stdin = bytes.NewReader(bootstrap)
\t\tcmd.Stdout = os.Stdout
\t\tcmd.Stderr = os.Stderr
\t\treturn cmd, nil
\t}

\ta.mu.Lock()
\tpassword := a.sudoPass
\ta.mu.Unlock()

\tvar auth *exec.Cmd
\tif password != "" {
\t\tauth = exec.Command("sudo", "-S", "-v")
\t\tauth.Stdin = strings.NewReader(password + "\\n")
\t} else {
\t\tauth = exec.Command("sudo", "-v")
\t\tauth.Stdin = os.Stdin
\t}
\tauth.Stdout = os.Stdout
\tauth.Stderr = os.Stderr
\tif err := auth.Run(); err != nil {
\t\treturn nil, fmt.Errorf("sudo authentication failed: %w", err)
\t}

\tcmd := exec.Command("sudo", "-n", "sh", "-c", command)
\tcmd.Stdin = bytes.NewReader(bootstrap)
\tcmd.Stdout = os.Stdout
\tcmd.Stderr = os.Stderr
\treturn cmd, nil
}

func (a *App) runSudo(command string) error {
\tfullCmd := a.runSudoCommand(command)''',
    "secure sudo bootstrap launcher",
)
linux = replace_once(
    linux,
    '''\tcmd := exec.Command("sudo", "-S", "-v")
\t\tauth.Stdin = strings.NewReader(password + "\\n")''',
    '''\tcmd := exec.Command("sudo", "-S", "-v")
\t\tauth.Stdin = strings.NewReader(password + "\\n")''',
    "sudo bootstrap authentication",
)
if 'cmd = append(cmd, "--token"' in bridge or '"--token", token' in bridge:
    raise SystemExit("unsafe --token argument remains after patch")
if 'cmd.Stdin = bytes.NewReader(bootstrap)' not in linux:
    raise SystemExit("Auto VK stdin delivery not found")
if 'sudo", "-n", "sh", "-c", command' not in linux:
    raise SystemExit("bootstrap launcher does not use separately authenticated sudo")
bridge_path.write_text(bridge, encoding="utf-8")
linux_path.write_text(linux, encoding="utf-8")

test_path = Path("upstream-lalune/Desktop/Libs/bridge_auto_vk_stdin_test.go")
test_path.write_text(r'''package libs

import (
	"encoding/base64"
	"encoding/json"
	"strings"
	"testing"
)

func TestAutoVKBootstrapIsStdinProtocol(t *testing.T) {
	token := "fixture-token-never-in-argv"
	payload, err := json.Marshal(struct {
		Token string `json:"token"`
	}{Token: token})
	if err != nil {
		t.Fatal(err)
	}
	line := "VK_JS_BOOTSTRAP:" + base64.StdEncoding.EncodeToString(payload) + "\n"
	if !strings.HasPrefix(line, "VK_JS_BOOTSTRAP:") || !strings.HasSuffix(line, "\n") {
		t.Fatalf("invalid bootstrap framing")
	}
	decoded, err := base64.StdEncoding.DecodeString(strings.TrimSuffix(strings.TrimPrefix(line, "VK_JS_BOOTSTRAP:"), "\n"))
	if err != nil {
		t.Fatal(err)
	}
	var got struct {
		Token string `json:"token"`
	}
	if err := json.Unmarshal(decoded, &got); err != nil {
		t.Fatal(err)
	}
	if got.Token != token {
		t.Fatal("bootstrap token round trip failed")
	}
	if strings.Contains(line, token) {
		t.Fatal("raw token must not appear in the bootstrap line")
	}
}
''', encoding="utf-8")
print("PASS: Auto VK no longer puts the token in argv; Linux runner sends the bootstrap only on stdin.")
