//go:build linux

package main

import (
    "context"
    "encoding/json"
    "fmt"
    "net/http"
    "os"
    "os/signal"
    "strconv"
    "strings"
    "syscall"
    "time"
)

const headlessListen = "127.0.0.1:1062"

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
            "core": "unknown",
            "ui": "0.6.0",
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

    srv := &http.Server{
        Addr:              headlessListen,
        Handler:           apiHandler(app),
        ReadHeaderTimeout: 5 * time.Second,
    }

    errCh := make(chan error, 1)
    go func() {
        app.core.AddLog(fmt.Sprintf("[INFO] Headless API: http://%s", headlessListen))
        errCh <- srv.ListenAndServe()
    }()

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
}
