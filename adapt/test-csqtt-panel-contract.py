#!/usr/bin/env python3
"""Contract checks for the packaged CSQTT-native panel and headless API.

This is deliberately a static contract test: it catches dead fixed buttons,
missing DOM targets, and UI requests that have no backend route before packaging.
Runtime/API behavior is additionally exercised by the ARM64 VM workflow.
"""
from pathlib import Path
import re
from html.parser import HTMLParser

HTML_PATH = Path("adapt/csqtt-panel-preview.html")
BACKEND_PATH = Path("adapt/headless_main.go")


class PanelParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.button_ids = []
        self.pages = []
        self.tabs = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "button" and attrs.get("id"):
            self.button_ids.append(attrs["id"])
        if tag == "section" and attrs.get("id", "").startswith("page-"):
            self.pages.append(attrs["id"][5:])
        if tag == "button" and attrs.get("data-page"):
            self.tabs.append(attrs["data-page"])


html = HTML_PATH.read_text(encoding="utf-8")
backend = BACKEND_PATH.read_text(encoding="utf-8")
scripts = re.findall(r"<script>(.*?)</script>", html, flags=re.S)
if not scripts:
    raise SystemExit("CSQTT panel has no inline JavaScript")
js = "\n".join(scripts)

parser = PanelParser()
parser.feed(html)
if len(parser.tabs) != 6 or set(parser.tabs) != {
    "connect", "settings", "deploy", "route", "logs", "info"
}:
    raise SystemExit(f"unexpected CSQTT tab contract: {parser.tabs}")
if len(parser.pages) != 6 or set(parser.pages) != set(parser.tabs):
    raise SystemExit(f"tab/page mismatch: tabs={parser.tabs}, pages={parser.pages}")

# Match the native CSQTT navigation order, not merely the same set of pages.
expected_tabs = ["connect", "settings", "deploy", "route", "logs", "info"]
if parser.tabs != expected_tabs:
    raise SystemExit(f"CSQTT tab order differs from original: {parser.tabs}")

# Keep the browser port on the native CSQTT brand palette and floating-tab
# visual language; do not drift back to the earlier generic blue-gray mock.
for token in ("--bg:#fdfdfe", "--surface2:#f2f2f4", "--blue:#1a73e8",
              "--blue2:#1565d8", "border-radius:24px", "backdrop-filter:blur(18px)"):
    if token not in html:
        raise SystemExit("native CSQTT visual token missing: " + token)


duplicate_ids = sorted({x for x in parser.button_ids if parser.button_ids.count(x) > 1})
if duplicate_ids:
    raise SystemExit("duplicate button IDs: " + ", ".join(duplicate_ids))

# Every statically declared button must have an explicit click handler.
# Profile-delete buttons are generated dynamically and are checked separately.
unbound = [
    button_id for button_id in parser.button_ids
    if f"$('{button_id}').addEventListener('click'" not in js
    and f'$("{button_id}").addEventListener("click"' not in js
]
if unbound:
    raise SystemExit("buttons without explicit click handlers: " + ", ".join(unbound))
if "delProfile" not in js or "addEventListener('click'" not in js:
    raise SystemExit("dynamic profile selection/deletion handlers are missing")

# Ensure all statically requested API paths are present in the backend mux.
api_paths = sorted(set(re.findall(r"req\(['\"](/[^'\"+]+)['\"]", js)))
routes = set(re.findall(r'mux\.HandleFunc\("([^"]+)"', backend))
missing_routes = []
for path in api_paths:
    if path in routes:
        continue
    if path.startswith("/configs/") and "/configs/" in routes:
        continue
    missing_routes.append(path)
if missing_routes:
    raise SystemExit("panel calls API paths missing from backend: " + ", ".join(missing_routes))

# Backend accepts both explicit manual mode and the core's selected-mode
# fallback; the panel must surface either only after connection was requested.
if "!['manual','selected'].includes(String(c.mode||'').toLowerCase())" not in js:
    raise SystemExit("panel does not expose selected-mode manual CAPTCHA fallback")
if "captchaArmed&&captchaIsActionable(c)" not in js:
    raise SystemExit("CAPTCHA overlay is not gated on an active connect session")

if "failed.push(names[i])" not in js or "'API частично · '+failed.length" not in js:
    raise SystemExit("background API failures are not reflected in panel status")

# Verify each independently fetched backend response updates its own UI state;
# a single failing endpoint must not discard successful responses from others.
for contract in (
    "if('configs'in data)state.configs",
    "if('selected'in data)state.selected",
    "if('settings'in data){state.settings",
    "if('status'in data){state.vpnStatus",
    "if('vk'in data)state.vk",
    "if('captcha'in data)state.captcha",
    "if('deployStatus'in data)state.deploying",
    "if('deployLog'in data)state.deployLog",
    "if('logs'in data)state.logs",
    "if('version'in data)state.version",
    "if(name==='info')refreshInfo()",
):
    if contract not in js:
        raise SystemExit("backend response is not applied to panel state: " + contract)


# Keep the user-facing route save explicit: it stores rules but must not claim
# that active routing changed immediately without a reconnect.
if "Переподключите CSQTT" not in html:
    raise SystemExit("Direct rules must explain that reconnect is required to apply changes")

print(
    f"CSQTT panel contract OK: {len(parser.button_ids)} fixed buttons, "
    f"{len(parser.tabs)} tabs, {len(api_paths)} API paths."
)
