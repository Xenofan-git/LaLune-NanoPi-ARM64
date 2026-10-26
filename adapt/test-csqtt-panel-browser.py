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
EXPECTED = {"connect", "settings", "deploy", "logs", "route"}
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
    vpn_connected = {"value": False}
    settings = {
        "authMode": "manual", "workers": 9, "autoApiWorkers": 9,
        "obfs": "video", "fingerprint": "firefox", "turnTransport": "udp",
        "captchaMode": "auto", "clientIds": "8202606,6287487",
        "directDomains": "", "directIPs": "", "deviceId": "fixture-device",
    }
    calls = []
    fail_paths = set()

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
        if path in fail_paths:
            route.fulfill(status=503, content_type="application/json", body=json.dumps({"error": "fixture unavailable"}))
            return
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
            body = {"connected": vpn_connected["value"]}
        elif path == "/vpn/connect" and method == "POST":
            vpn_connected["value"] = True
            body = {"ok": True}
        elif path == "/vpn/disconnect" and method == "POST":
            vpn_connected["value"] = False
            body = {"ok": True}
        elif path == "/vk/state":
            body = {"hasToken": False, "fetching": False}
        elif path == "/captcha/state":
            body = {"pending": False}
        elif path == "/captcha/result" and method == "POST":
            body = {"ok": True}
        elif path == "/deploy/status":
            body = {"deploying": False}
        elif path == "/deploy/log":
            body = ""
        elif path == "/version":
            body = {"backend": "fixture", "ui": "test"}
        elif path == "/logs":
            body = []
        elif path == "/logs/clear" and method == "POST":
            body = {"ok": True}
        elif path == "/deploy" and method == "POST":
            body = {"ok": True}
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
            page.on("dialog", lambda dialog: dialog.accept())
            page.route("**/api/**", api_fixture)
            page.goto(base_url, wait_until="domcontentloaded")
            page.wait_for_function("document.querySelector('#profileList .profile') !== null")
            page.wait_for_timeout(100)

            tabs = page.locator("button[data-page]")
            actual = [tabs.nth(i).get_attribute("data-page") for i in range(tabs.count())]
            assert len(actual) == 5 and set(actual) == EXPECTED, f"five-tab set mismatch: {actual}"

            for name in EXPECTED:
                page.locator(f'button[data-page="{name}"]').click()
                assert page.locator(f"#page-{name}").evaluate(
                    "(el) => el.classList.contains('active')"
                ), f"tab did not activate: {name}"
                assert page.locator(f'button[data-page="{name}"]').get_attribute("aria-current") == "page", (
                    f"active tab missing aria-current state: {name}"
                )
                assert page.locator(f'button[data-page="{name}"]').get_attribute("aria-pressed") is None

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
            assert page.locator("#vkHashes").evaluate("el => el.readOnly")

            # Connect tab: power button must send connect and disconnect actions.
            page.locator("#power").click()
            page.wait_for_function("""() => document.querySelector("#toast").textContent.includes("Подключение запрошено")""")
            page.wait_for_function("""() => document.querySelector("#power").getAttribute("aria-pressed") === "true" """)
            page.locator("#power").click()
            page.wait_for_function("""() => document.querySelector("#toast").textContent.includes("Отключение запрошено")""")
            page.wait_for_function("""() => document.querySelector("#power").getAttribute("aria-pressed") === "false" """)
            assert any(method == "POST" and path == "/vpn/connect" for method, path, _ in calls)
            assert any(method == "POST" and path == "/vpn/disconnect" for method, path, _ in calls)

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

            # Tunnel settings: changing the worker count must persist through /settings.
            page.locator('button[data-page="settings"]').click()
            page.locator("#workers").evaluate("""el => {
              el.value = "11";
              el.dispatchEvent(new Event("input", {bubbles:true}));
            }""")
            page.locator("#saveSettings").click()
            page.wait_for_function("""() => document.querySelector("#workersValue").textContent === "11" """)
            saved_settings = [json.loads(raw) for method, path, raw in calls
                              if method == "POST" and path == "/settings" and raw]
            assert saved_settings and saved_settings[-1]["workers"] == 11, (
                "Tunnel settings were not persisted"
            )

            # Logs: refresh reads the log endpoint and clear sends the explicit POST.
            page.locator('button[data-page="logs"]').click()
            page.locator("#refreshLogs").click()
            page.wait_for_function("""() => document.querySelector("#logs").textContent.includes("Записей пока нет")""")
            assert any(method == "GET" and path == "/logs" for method, path, _ in calls), (
                "Logs tab did not load /logs"
            )
            page.locator("#clearLogs").click()
            page.wait_for_function("""() => document.querySelector("#toast").textContent.includes("Журнал очищен")""")
            assert any(method == "POST" and path == "/logs/clear" for method, path, _ in calls), (
                "Logs clear action did not reach backend"
            )

            # Deploy: validate the one-button flow against a deterministic API fixture.
            # This proves the page constructs the expected request without SSHing anywhere.
            page.locator('button[data-page="deploy"]').click()
            page.locator("#deployHost").fill("192.0.2.50")
            page.locator("#deployPassword").fill("fixture-ssh-password")
            page.locator("#editDeployAuth").click()
            page.locator("#mainPassword").fill("fixturetunnelpassword")
            page.locator("#webLogin").fill("fixtureadmin")
            page.locator("#webPassword").fill("fixturewebpassword")
            page.locator("#saveDeployAuth").click()
            page.wait_for_function("""() => document.querySelector("#deploySecretsOverlay").classList.contains("hidden")""")
            page.locator("#startDeploy").click()
            page.wait_for_function("""() => document.querySelector("#toast").textContent.includes("Деплой запущен")""")
            deploy_requests = [json.loads(raw) for method, path, raw in calls
                               if method == "POST" and path == "/deploy" and raw]
            assert deploy_requests, "Deploy button did not call /deploy"
            assert deploy_requests[-1]["host"] == "192.0.2.50"
            assert deploy_requests[-1]["deviceId"] == "fixture-device"
            assert deploy_requests[-1]["corePort"] == 47000 and deploy_requests[-1]["warpPort"] == 47002

            # A failed status endpoint must not be misreported as a real disconnect,
            # and deployment actions must remain blocked when operation state is unknown.
            fail_paths.update({"/vpn/status", "/deploy/status", "/deploy/log"})
            page.reload(wait_until="domcontentloaded")
            page.wait_for_function("document.querySelector('#apiStatus').textContent.includes('API')")
            assert page.locator("#connState").inner_text() == "Статус недоступен", "VPN API failure was presented as disconnected"
            assert page.locator("#power").is_disabled(), "connect toggle stayed enabled while VPN state was unknown"
            assert "Не удалось получить состояние деплоя" in page.locator("#deployState").inner_text(), "unknown deploy state was presented as a completed/idle operation"
            assert page.locator("#startDeploy").is_disabled(), "deploy remained enabled while deploy state was unknown"
            assert not page_errors, f"uncaught browser errors: {page_errors}"

            # Exercise the real CAPTCHA Bridge on a distinct origin. It must
            # navigate back to the panel and submit via same-origin /api.
            bridge_source = (ROOT / "captcha-bridge" / "captcha-bridge.js").read_text()
            bridge_page = browser.new_page()
            bridge_page.add_init_script(bridge_source)
            bridge_page.route("**/api/**", api_fixture)
            panel_origin = f"http://127.0.0.1:{server.server_port}"
            vk_origin = f"http://localhost:{server.server_port}"
            bridge_page.route(
                panel_origin + "/",
                lambda route: route.fulfill(
                    status=200, content_type="text/html", body=HTML.read_text()
                ),
            )
            bridge_page.route(
                "**/captchaNotRobot.check",
                lambda route: route.fulfill(
                    status=200,
                    content_type="application/json",
                    body=json.dumps({"response": {"success_token": "fixture-bridge-success-token"}}),
                ),
            )
            encoded_panel_origin = panel_origin.replace(":", "%3A").replace("/", "%2F")
            bridge_page.goto(
                vk_origin + "/adapt/csqtt-panel-preview.html#"
                + "lalune_panel=" + encoded_panel_origin
                + "&lalune_session=fixture-bridge-session",
                wait_until="domcontentloaded",
            )
            bridge_page.evaluate("() => { void fetch('/captchaNotRobot.check'); }")
            bridge_page.wait_for_url(panel_origin + "/", timeout=10000)
            bridge_page.wait_for_function(
                "() => document.querySelector('#toast').textContent.includes('CAPTCHA автоматически передана')",
                timeout=10000,
            )
            bridge_posts = [
                json.loads(raw) for method, path, raw in calls
                if method == "POST" and path == "/captcha/result" and raw
            ]
            assert bridge_posts and bridge_posts[-1] == {
                "sessionToken": "fixture-bridge-session",
                "result": "fixture-bridge-success-token",
            }, f"CAPTCHA bridge did not reach panel same-origin API: {bridge_posts!r}"
            bridge_page.close()
            browser.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
    print("CSQTT_CHROMIUM_UI_SMOKE_PASS widths=320,360,390,768,1280 tabs=5 profile-api=PASS connect-disconnect=PASS tunnel-settings=PASS direct-settings-api=PASS deploy-api=PASS logs=PASS captcha-bridge-same-origin=PASS")


if __name__ == "__main__":
    main()
