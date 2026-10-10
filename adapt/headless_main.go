//go:build linux

package main

import (
    "sync"
    "context"
    "embed"
    "io/fs"
    "encoding/json"
    "fmt"
    "net"
    "net/http"
    "net/url"
    "os"
    "os/signal"
    "strconv"
    "strings"
    "syscall"
    "time"

    "lalune-desktop/Libs"
)

const headlessListen = "127.0.0.1:1062"
const panelListen = "0.0.0.0:1061"

// Set by the pinned ARM64 build workflow through Go -ldflags.
var (
    buildCommit = "unknown"
    buildRunID = "unknown"
    buildRunNumber = "unknown"
    buildDate = "unknown"
    buildBranch = "unknown"
    buildUpstreamCommit = "unknown"
)

//go:embed frontend
var panelAssets embed.FS

type connectBody struct {
    ID int64 `json:"id"`
}

type configBody struct {
    Link     string `json:"link"`
    Protocol string `json:"protocol"`
}

func writeRaw(w http.ResponseWriter, value string) {
    w.Header().Set("Content-Type", "application/json; charset=utf-8")
    w.WriteHeader(http.StatusOK)
    _, _ = w.Write([]byte(value))
}

func mustJSON(value string) string { b, _ := json.Marshal(value); return string(b) }

func writeJSON(w http.ResponseWriter, value any) {
    w.Header().Set("Content-Type", "application/json; charset=utf-8")
    _ = json.NewEncoder(w).Encode(value)
}

func method(w http.ResponseWriter, r *http.Request, want string) bool {
    if r.Method != want {
        w.Header().Set("Allow", want)
        http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
        return false
    }
    return true
}

// privateClient permits sensitive operations only from a private LAN or the
// Tailscale address range. Nginx overwrites X-Real-IP and the backend binds to
// loopback, so a remote caller cannot choose this header directly.
func privateClient(r *http.Request) bool {
    raw := strings.TrimSpace(r.Header.Get("X-Real-IP"))
    if raw == "" {
        raw = r.RemoteAddr
        if host, _, err := net.SplitHostPort(raw); err == nil {
            raw = host
        }
    }
    ip := net.ParseIP(strings.Trim(raw, "[]"))
    if ip == nil {
        return false
    }
    if ip.IsLoopback() || ip.IsPrivate() || ip.IsLinkLocalUnicast() {
        return true
    }
    _, tailscaleIPv4, _ := net.ParseCIDR("100.64.0.0/10")
    if tailscaleIPv4.Contains(ip) {
        return true
    }
    _, tailscaleIPv6, _ := net.ParseCIDR("fd7a:115c:a1e0::/48")
    return tailscaleIPv6.Contains(ip)
}

var captchaMu sync.Mutex
var captchaPending bool
var captchaMode string
var captchaRedirectURI string
var captchaSessionToken string
var captchaHandledSession string
var captchaUpdated time.Time

func captchaRequestIsActive(mode, redirectURI string, now time.Time) bool {
    // Automatic CAPTCHA events are internal retries and must never trigger UI.
    if !strings.EqualFold(strings.TrimSpace(mode), "manual") {
        return false
    }
    // VK challenge links include an explicit expiry. Do not resurrect an old
    // challenge from the persistent application log after it has expired.
    u, err := url.Parse(redirectURI)
    if err != nil {
        return false
    }
    expires := strings.TrimSpace(u.Query().Get("expired_at"))
    if expires == "" {
        return false
    }
    unix, err := strconv.ParseInt(expires, 10, 64)
    if err != nil || unix <= now.Unix() {
        return false
    }
    return true
}

func refreshCaptchaState(app *App) {
    raw := app.GetLogsJson()
    var logs []string
    if json.Unmarshal([]byte(raw), &logs) != nil { return }
    captchaMu.Lock()
    defer captchaMu.Unlock()
    // The newest CAPTCHA_SOLVE event is authoritative for this moment. This
    // allows a later manual fallback event to supersede an earlier auto event.
    for i := len(logs)-1; i >= 0; i-- {
        parts := strings.SplitN(strings.TrimSpace(logs[i]), "|", 4)
        if len(parts) != 4 || parts[0] != "CAPTCHA_SOLVE" { continue }
        session := strings.TrimSpace(parts[3])
        if session == "" || session == captchaHandledSession {
            captchaPending = false
            captchaMode = ""
            captchaRedirectURI = ""
            captchaSessionToken = ""
            captchaUpdated = time.Time{}
            return
        }
        if !captchaRequestIsActive(parts[1], parts[2], time.Now()) {
            captchaPending = false
            captchaMode = ""
            captchaRedirectURI = ""
            captchaSessionToken = ""
            captchaUpdated = time.Time{}
            return
        }
        if captchaSessionToken != session || !captchaPending {
            captchaUpdated = time.Now()
        }
        captchaPending = true
        captchaMode = strings.TrimSpace(parts[1])
        captchaRedirectURI = parts[2]
        captchaSessionToken = session
        return
    }
    // No CAPTCHA event in the current log: clear any in-memory stale state.
    captchaPending = false
    captchaMode = ""
    captchaRedirectURI = ""
    captchaSessionToken = ""
    captchaUpdated = time.Time{}
}

func captchaState(app *App) map[string]any {
    refreshCaptchaState(app)
    captchaMu.Lock(); defer captchaMu.Unlock()
    return map[string]any{"pending": captchaPending, "mode": captchaMode, "redirectUri": captchaRedirectURI, "sessionToken": captchaSessionToken, "updated": captchaUpdated.UnixMilli()}
}

func finishCaptcha(app *App, sessionToken, result string) bool {
    captchaMu.Lock()
    if !captchaPending || sessionToken == "" || sessionToken != captchaSessionToken { captchaMu.Unlock(); return false }
    captchaMu.Unlock()
    result = strings.TrimSpace(result)
    if result == "" || len(result) > 16384 || strings.ContainsAny(result, "\r\n") { return false }
    if app.runner == nil || !app.runner.SubmitCaptchaResult(result) { return false }
    captchaMu.Lock(); captchaHandledSession = sessionToken; captchaPending = false; captchaMode = ""; captchaRedirectURI = ""; captchaSessionToken = ""; captchaUpdated = time.Time{}; captchaMu.Unlock()
    return true
}
var vkAutoMu sync.Mutex
var vkAutoResult = "{\"pending\":false}"
var vkAutoRunning bool

func apiHandler(app *App) http.Handler {
    mux := http.NewServeMux()

    mux.HandleFunc("/ping", func(w http.ResponseWriter, r *http.Request) {
        if !method(w, r, http.MethodGet) { return }
        writeJSON(w, map[string]any{"ok": true})
    })

    mux.HandleFunc("/version", func(w http.ResponseWriter, r *http.Request) {
        if !method(w, r, http.MethodGet) { return }
        writeJSON(w, map[string]any{
            "api": 1,
            "backend": "original-go",
            "core": "csqtt-server/2.1.9",
            "ui": "0.6.0",
            "commit": buildCommit,
            "buildRun": buildRunID,
            "buildNumber": buildRunNumber,
            "buildDate": buildDate,
            "buildBranch": buildBranch,
            "upstreamCommit": buildUpstreamCommit,
        })
    })

    mux.HandleFunc("/configs", func(w http.ResponseWriter, r *http.Request) {
        switch r.Method {
        case http.MethodGet:
            writeRaw(w, app.GetConfigsJson())
        case http.MethodPost:
            var body configBody
            if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
                http.Error(w, "bad json", http.StatusBadRequest)
                return
            }
            if body.Link == "" {
                http.Error(w, "link is required", http.StatusBadRequest)
                return
            }
            ok := app.SaveConfigWithProtocol(body.Link, body.Protocol)
            writeJSON(w, map[string]bool{"ok": ok})
        default:
            w.Header().Set("Allow", "GET, POST")
            http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
        }
    })

    mux.HandleFunc("/configs/selected", func(w http.ResponseWriter, r *http.Request) {
        switch r.Method {
        case http.MethodGet:
            writeRaw(w, app.GetSelectedConfigJson())
        case http.MethodPut, http.MethodPost:
            var raw json.RawMessage
            if err := json.NewDecoder(r.Body).Decode(&raw); err != nil {
                http.Error(w, "bad json", http.StatusBadRequest)
                return
            }
            writeJSON(w, map[string]bool{"ok": app.SetSelectedConfigJson(string(raw))})
        default:
            w.Header().Set("Allow", "GET, PUT, POST")
            http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
        }
    })

    mux.HandleFunc("/configs/", func(w http.ResponseWriter, r *http.Request) {
        idText := strings.TrimPrefix(r.URL.Path, "/configs/")
        id, err := strconv.ParseInt(idText, 10, 64)
        if err != nil {
            http.Error(w, "invalid config id", http.StatusBadRequest)
            return
        }
        if !method(w, r, http.MethodDelete) { return }
        writeJSON(w, map[string]bool{"ok": app.DeleteConfig(id)})
    })

    mux.HandleFunc("/settings", func(w http.ResponseWriter, r *http.Request) {
        switch r.Method {
        case http.MethodGet:
            writeRaw(w, app.GetSettingsJson())
        case http.MethodPut, http.MethodPost:
            var raw json.RawMessage
            if err := json.NewDecoder(r.Body).Decode(&raw); err != nil {
                http.Error(w, "bad json", http.StatusBadRequest)
                return
            }
            writeJSON(w, map[string]bool{"ok": app.SaveSettings(string(raw))})
        default:
            w.Header().Set("Allow", "GET, PUT, POST")
            http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
        }
    })

    mux.HandleFunc("/settings/reset", func(w http.ResponseWriter, r *http.Request) {
        if !method(w, r, http.MethodPost) { return }
        http.Error(w, "settings reset is not implemented by pinned LaLune", http.StatusNotImplemented)
    })

    mux.HandleFunc("/vpn/status", func(w http.ResponseWriter, r *http.Request) {
        if !method(w, r, http.MethodGet) { return }
        writeRaw(w, app.GetStatusJson())
    })

    mux.HandleFunc("/vpn/connect", func(w http.ResponseWriter, r *http.Request) {
        if !method(w, r, http.MethodPost) { return }
        var body connectBody
        if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
            http.Error(w, "bad json", http.StatusBadRequest)
            return
        }
        writeJSON(w, map[string]bool{"ok": app.Connect(body.ID)})
    })

    mux.HandleFunc("/vpn/disconnect", func(w http.ResponseWriter, r *http.Request) {
        if !method(w, r, http.MethodPost) { return }
        writeJSON(w, map[string]bool{"ok": app.Disconnect()})
    })

    mux.HandleFunc("/vpn/reconnect", func(w http.ResponseWriter, r *http.Request) {
        if !method(w, r, http.MethodPost) { return }
        var body connectBody
        if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
            http.Error(w, "bad json", http.StatusBadRequest)
            return
        }
        _ = app.Disconnect()
        writeJSON(w, map[string]bool{"ok": app.Connect(body.ID)})
    })

    mux.HandleFunc("/logs", func(w http.ResponseWriter, r *http.Request) {
        if !method(w, r, http.MethodGet) { return }
        writeRaw(w, app.GetLogsJson())
    })

    mux.HandleFunc("/logs/tail", func(w http.ResponseWriter, r *http.Request) {
        if !method(w, r, http.MethodGet) { return }
        writeRaw(w, app.GetLogsJson())
    })

    mux.HandleFunc("/logs/clear", func(w http.ResponseWriter, r *http.Request) {
        if !method(w, r, http.MethodPost) { return }
        writeJSON(w, map[string]bool{"ok": app.ClearLogs()})
    })

    mux.HandleFunc("/deploy", func(w http.ResponseWriter, r *http.Request) {
        if !method(w, r, http.MethodPost) { return }
        if !privateClient(r) {
            http.Error(w, "deployment is available only from LAN or Tailscale", http.StatusForbidden)
            return
        }
        var raw json.RawMessage
        if err := json.NewDecoder(r.Body).Decode(&raw); err != nil { http.Error(w, "bad json", http.StatusBadRequest); return }
        writeJSON(w, map[string]bool{"ok": libs.DeployProtocol(string(raw))})
    })
    mux.HandleFunc("/deploy/log", func(w http.ResponseWriter, r *http.Request) {
        if !method(w, r, http.MethodGet) { return }
        if !privateClient(r) {
            http.Error(w, "deployment status is available only from LAN or Tailscale", http.StatusForbidden)
            return
        }
        writeRaw(w, mustJSON(libs.DeployLog()))
    })
    mux.HandleFunc("/deploy/status", func(w http.ResponseWriter, r *http.Request) {
        if !method(w, r, http.MethodGet) { return }
        if !privateClient(r) {
            http.Error(w, "deployment status is available only from LAN or Tailscale", http.StatusForbidden)
            return
        }
        writeJSON(w, map[string]bool{"deploying": libs.DeployBusy()})
    })

    mux.HandleFunc("/updates/core", func(w http.ResponseWriter, r *http.Request) {
        if !method(w, r, http.MethodPost) { return }
        writeJSON(w, map[string]bool{"ok": app.UpdateCore()})
    })
    mux.HandleFunc("/updates/core/wait", func(w http.ResponseWriter, r *http.Request) {
        if !method(w, r, http.MethodPost) { return }
        writeJSON(w, map[string]bool{"ok": app.UpdateCoreAndWait()})
    })
    mux.HandleFunc("/updates/core/check", func(w http.ResponseWriter, r *http.Request) {
        if !method(w, r, http.MethodGet) { return }
        writeRaw(w, app.CheckUpdate())
    })
    mux.HandleFunc("/updates/core/status", func(w http.ResponseWriter, r *http.Request) {
        if !method(w, r, http.MethodGet) { return }
        writeJSON(w, map[string]bool{"downloading": app.IsCoreDownloading()})
    })
    mux.HandleFunc("/updates/lalune", func(w http.ResponseWriter, r *http.Request) {
        if !method(w, r, http.MethodGet) { return }
        writeJSON(w, app.CheckLaLuneUpdate())
    })
    mux.HandleFunc("/vk/state", func(w http.ResponseWriter, r *http.Request) {
        if !method(w, r, http.MethodGet) { return }
        writeJSON(w, app.GetVKTokenState())
    })
    mux.HandleFunc("/vk/login", func(w http.ResponseWriter, r *http.Request) {
        if !method(w, r, http.MethodPost) { return }
        writeJSON(w, map[string]bool{"ok": app.LoginVK()})
    })
    mux.HandleFunc("/vk/import", func(w http.ResponseWriter, r *http.Request) {
        if !method(w, r, http.MethodPost) { return }
        if !privateClient(r) { http.Error(w, "forbidden", http.StatusForbidden); return }
        var req struct { Token string `json:"token"` }
        if err := json.NewDecoder(http.MaxBytesReader(w, r.Body, 8192)).Decode(&req); err != nil {
            w.WriteHeader(http.StatusBadRequest)
            writeJSON(w, map[string]any{"ok": false, "error": "Некорректный запрос"})
            return
        }
        if err := app.core.SaveVKTokenInput(req.Token); err != nil {
            w.WriteHeader(http.StatusBadRequest)
            writeJSON(w, map[string]any{"ok": false, "error": err.Error()})
            return
        }
        writeJSON(w, map[string]bool{"ok": true})
    })
    mux.HandleFunc("/vk/delete", func(w http.ResponseWriter, r *http.Request) {
        if !method(w, r, http.MethodPost) { return }
        writeJSON(w, map[string]bool{"ok": app.DeleteVKToken()})
    })
    mux.HandleFunc("/vk/validate", func(w http.ResponseWriter, r *http.Request) {
        if !method(w, r, http.MethodGet) { return }
        writeJSON(w, app.ValidateVKToken())
    })
    mux.HandleFunc("/vk/auto", func(w http.ResponseWriter, r *http.Request) {
        if !method(w, r, http.MethodPost) { return }
        vkAutoMu.Lock()
        if vkAutoRunning { vkAutoMu.Unlock(); writeRaw(w, "{\"pending\":true}"); return }
        vkAutoRunning = true; vkAutoResult = "{\"pending\":true}"; vkAutoMu.Unlock()
        go func() { result := app.RunVkAutoApiCalls(); vkAutoMu.Lock(); vkAutoResult = result; vkAutoRunning = false; vkAutoMu.Unlock() }()
        writeRaw(w, "{\"pending\":true}")
    })
    mux.HandleFunc("/vk/auto/poll", func(w http.ResponseWriter, r *http.Request) {
        if !method(w, r, http.MethodGet) { return }
        vkAutoMu.Lock(); result := vkAutoResult; vkAutoMu.Unlock(); writeRaw(w, result)
    })
    mux.HandleFunc("/vk/finish", func(w http.ResponseWriter, r *http.Request) {
        if !method(w, r, http.MethodPost) { return }
        var ids []string
        if err := json.NewDecoder(r.Body).Decode(&ids); err != nil { http.Error(w, "bad json", http.StatusBadRequest); return }
        writeJSON(w, map[string]bool{"ok": app.FinishVkCalls(ids)})
    })

    mux.HandleFunc("/captcha/state", func(w http.ResponseWriter, r *http.Request) {
        if !method(w, r, http.MethodGet) { return }
        writeJSON(w, captchaState(app))
    })
    mux.HandleFunc("/captcha/result", func(w http.ResponseWriter, r *http.Request) {
        if !method(w, r, http.MethodPost) { return }
        var body struct { SessionToken string `json:"sessionToken"`; Result string `json:"result"` }
        if err := json.NewDecoder(r.Body).Decode(&body); err != nil { http.Error(w, "bad json", http.StatusBadRequest); return }
        writeJSON(w, map[string]bool{"ok": finishCaptcha(app, body.SessionToken, body.Result)})
    })
    mux.HandleFunc("/captcha/cancel", func(w http.ResponseWriter, r *http.Request) {
        if !method(w, r, http.MethodPost) { return }
        captchaMu.Lock(); token := captchaSessionToken; captchaMu.Unlock()
        ok := token != "" && finishCaptcha(app, token, "error:cancelled")
        writeJSON(w, map[string]bool{"ok": ok})
    })
    mux.HandleFunc("/shutdown", func(w http.ResponseWriter, r *http.Request) {
        if !method(w, r, http.MethodPost) { return }
        writeJSON(w, map[string]bool{"ok": true})
        go func() {
            time.Sleep(100 * time.Millisecond)
            _ = syscall.Kill(os.Getpid(), syscall.SIGTERM)
        }()
    })

    return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
        w.Header().Set("Access-Control-Allow-Origin", "*")
        w.Header().Set("Access-Control-Allow-Headers", "Content-Type, Authorization")
        w.Header().Set("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")
        if r.Method == http.MethodOptions {
            w.WriteHeader(http.StatusNoContent)
            return
        }
        mux.ServeHTTP(w, r)
    })
}

func main() {
    app := NewApp()
    app.startup(context.Background())

    api := apiHandler(app)
    srv := &http.Server{Addr: headlessListen, Handler: api, ReadHeaderTimeout: 5 * time.Second}
    panelFS, _ := fs.Sub(panelAssets, "frontend")
    panelHandler := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
        if r.URL.Path == "/api" || strings.HasPrefix(r.URL.Path, "/api/") {
            u := *r.URL
            u.Path = strings.TrimPrefix(r.URL.Path, "/api")
            if u.Path == "" { u.Path = "/" }
            rr := r.Clone(r.Context()); rr.URL = &u
            api.ServeHTTP(w, rr)
            return
        }
        p := strings.TrimPrefix(r.URL.Path, "/")
        if p == "" { p = "index.html" }
        if _, err := fs.Stat(panelFS, p); err != nil { p = "index.html" }
        http.ServeFileFS(w, r, panelFS, p)
    })
    panelSrv := &http.Server{Addr: panelListen, Handler: panelHandler, ReadHeaderTimeout: 5 * time.Second}

    errCh := make(chan error, 2)
    go func() { app.core.AddLog(fmt.Sprintf("[INFO] Headless API: http://%s", headlessListen)); errCh <- srv.ListenAndServe() }()
    go func() { app.core.AddLog(fmt.Sprintf("[INFO] LaLune panel: http://%s", panelListen)); errCh <- panelSrv.ListenAndServe() }()

    sigCh := make(chan os.Signal, 1)
    signal.Notify(sigCh, syscall.SIGINT, syscall.SIGTERM)

    select {
    case sig := <-sigCh:
        app.core.AddLog(fmt.Sprintf("[INFO] Shutdown signal: %s", sig))
    case err := <-errCh:
        app.core.AddLog(fmt.Sprintf("[ERROR] Headless API stopped: %v", err))
    }

    _ = app.Disconnect()
    _ = srv.Shutdown(context.Background())
    _ = panelSrv.Shutdown(context.Background())
}