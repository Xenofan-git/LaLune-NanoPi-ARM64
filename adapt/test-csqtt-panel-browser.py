#!/usr/bin/env python3
"""Chromium UI smoke and API-contract interaction tests for the CSQTT panel.

The actual panel is served over HTTP. API calls are intercepted with a deterministic
fixture, so profile selection/settings persistence are exercised without touching
a real account, VK token, server, or network.
"""
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import threading

from playwright.sync_api import sync_playwright

ROOT = Path(".").resolve()
HTML = ROOT / "adapt" / "csqtt-panel-preview.html"
EXPECTED = ["connect", "settings", "deploy", "route", "logs", "info"]
WIDTHS = [320, 360, 390, 768, 1280]


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *_args):
        pass


def main():
    profiles = [
        {"id": 1, "name": "Profile one", "protocol": "CSQTT", "hashes": "hash-one"},
        {"id": 2, "name": "Profile two", "protocol": "CSQTT", "hashes": "hash-two"},
    ]
    selected = {"profile": profiles[0]}
    settings = {
        "authMode": "manual", "workers": 9, "autoApiWorkers": 9,
        "obfs": "video", "fingerprint": "firefox", "turnTransport": "udp",
        "captchaMode": "auto", "clientIds": "8202606,6287487",
        "directDomains": "", "directIPs": "", "deviceId": "fixture-device",
    }
    calls = []

    server = ThreadingHTTPServer(
        ("127.0.0.1", 0), partial(QuietHandler, directory=str(ROOT))
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{server.server_port}/adapt/csqtt-panel-preview.html"

    def api_fixture(route):
        request = route.request
        from urllib.parse import urlparse
        path = urlparse(request.url).path.removeprefix("/api")
        method = request.method
        calls.append((method, path, request.post_data))
        body = {}
        status = 200
        if path == "/configs" and method == "GET":
            body = profiles
        elif path == "/configs/selected" and method == "GET":
            body = selected["profile"]
        elif path == "/configs/selected" and method in ("POST", "PUT"):
            candidate = json.loads(request.post_data or "{}")
            selected["profile"] = candidate
            body = {"ok": True}
        elif path == "/settings" and method == "GET":
            body = settings
        elif path == "/settings" and method in ("POST", "PUT"):
            settings.clear()
            settings.update(json.loads(request.post_data or "{}"))
            body = {"ok": True}
        elif path == "/vpn/status":
            body = {"connected": False}
        elif path == "/vk/state":
            body = {"hasToken": False, "fetching": False}
        elif path == "/captcha/state":
            body = {"pending": False}
        elif path == "/deploy/status":
            body = {"deploying": False}
        elif path == "/deploy/log":
            body = ""
        elif path == "/version":
            body = {"backend": "fixture", "ui": "test"}
        elif path == "/logs":
            body = []
        elif path == "/updates/lalune":
            body = {"hasUpdate": False}
        else:
            status = 404
            body = {"error": f"unexpected API request: {method} {path}"}
        route.fulfill(status=status, content_type="application/json", body=json.dumps(body))

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page_errors = []
            page.on("pageerror", lambda error: page_errors.append(str(error)))
            page.route("**/api/**", api_fixture)
            page.goto(base_url, wait_until="domcontentloaded")
            page.wait_for_function("document.querySelector('#profileList .profile') !== null")
            page.wait_for_timeout(100)

            tabs = page.locator("button[data-page]")
            actual = [tabs.nth(i).get_attribute("data-page") for i in range(tabs.count())]
            assert actual == EXPECTED, f"tab order mismatch: {actual}"

            for name in EXPECTED:
                page.locator(f'button[data-page="{name}"]').click()
                assert page.locator(f"#page-{name}").evaluate(
                    "(el) => el.classList.contains('active')"
                ), f"tab did not activate: {name}"

            for width in WIDTHS:
                page.set_viewport_size({"width": width, "height": 850})
                page.wait_for_timeout(40)
                dimensions = page.evaluate("""() => ({
                  viewport: innerWidth,
                  document: document.documentElement.scrollWidth,
                  nav: (() => { const r=document.querySelector('.tabs').getBoundingClientRect();
                    return {left:r.left,right:r.right,width:r.width}; })()
                })""")
                assert dimensions["document"] <= width, (
                    f"horizontal overflow at {width}px: {dimensions}"
                )
                assert dimensions["nav"]["left"] >= -1 and dimensions["nav"]["right"] <= width + 1, (
                    f"bottom navigation escapes viewport at {width}px: {dimensions}"
                )

            # Selecting another profile must round-trip through the API and refresh
            # the profile-specific hash shown on the Tunnel page.
            page.locator('button[data-page="connect"]').click()
            page.locator('.profile[data-id="2"]').click()
            page.wait_for_function("document.querySelector('#vkHashes').value === 'hash-two'")
            assert any(m == "POST" and path == "/configs/selected" for m, path, _ in calls), (
                "profile selection did not reach backend API"
            )
            assert page.locator("#vkHashes").is_disabled() is False
            assert page.locator("#vkHashes").is_read_only()

            # Direct rules are validated and persisted through the settings API.
            page.locator('button[data-page="route"]').click()
            page.locator("#directDomains").fill("example.com\ncdn.example.com")
            page.locator("#directIPs").fill("192.0.2.10\n192.0.2.0/24")
            page.locator("#saveDirectRules").click()
            page.wait_for_function("document.querySelector('#routeMessage').textContent.includes('Правила сохранены')")
            saved = [json.loads(raw) for method, path, raw in calls
                     if method == "POST" and path == "/settings" and raw]
            assert saved and saved[-1]["directDomains"] == "example.com\ncdn.example.com", (
                "Direct domains were not persisted by the settings API"
            )
            assert saved[-1]["directIPs"] == "192.0.2.10\n192.0.2.0/24", (
                "Direct IP rules were not persisted by the settings API"
            )

            assert page.locator("#page-route").is_visible()
            assert not page.locator("#deploySecretsOverlay").is_visible()
            assert not page_errors, f"uncaught browser errors: {page_errors}"
            browser.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
    print("CSQTT_CHROMIUM_UI_SMOKE_PASS widths=320,360,390,768,1280 tabs=6 profile-api=PASS direct-settings-api=PASS")


if __name__ == "__main__":
    main()
