//go:build linux

package main

import (
    "os"
    "os/exec"
    "path/filepath"
    "strings"
    "testing"
)

func TestCSQTTCredentialsReachSpawnedCoreArgv(t *testing.T) {
    deviceID := "01234567-89ab-cdef-0123-456789abcdef"
    password := "argv-secret-with-'-quote"
    dir := t.TempDir()
    argvFile := filepath.Join(dir, "argv.txt")
    core := filepath.Join(dir, "fake-csqtt-core")
    script := "#!/bin/sh\nprintf '%s\\n' \"$@\" > " + shellQuoteForTest(argvFile) + "\n"
    if err := os.WriteFile(core, []byte(script), 0700); err != nil { t.Fatal(err) }

    // Exercise the same helper used by LinuxRunner.StartCore, then execute
    // the exact production shell command builder and inspect the child argv.
    args := appendCSQTTAuthArgs([]string{core, "--listen", "127.0.0.1:52230"}, password, deviceID)
    commandLine := buildCoreCommandLine(args, filepath.Join(dir, "core.log"))
    if err := exec.Command("sh", "-c", commandLine).Run(); err != nil {
        t.Fatalf("spawn core command: %v", err)
    }
    got, err := os.ReadFile(argvFile)
    if err != nil { t.Fatal(err) }
    lines := strings.Split(strings.TrimSpace(string(got)), "\n")
    want := []string{"--listen", "127.0.0.1:52230", "-device-id", deviceID, "-password", password}
    if len(lines) != len(want) { t.Fatalf("child argv = %#v, want %#v", lines, want) }
    for i := range want {
        if lines[i] != want[i] { t.Fatalf("child argv[%d] = %q, want %q; all=%#v", i, lines[i], want[i], lines) }
    }
}

func shellQuoteForTest(value string) string {
    return "'" + strings.ReplaceAll(value, "'", "'\\''") + "'"
}
