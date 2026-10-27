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
if len(parser.tabs) != 5 or set(parser.tabs) != {
    "connect", "settings", "deploy", "route", "logs"
}:
    raise SystemExit(f"unexpected CSQTT tab contract: {parser.tabs}")
if len(parser.pages) != 5 or set(parser.pages) != set(parser.tabs):
    raise SystemExit(f"tab/page mismatch: tabs={parser.tabs}, pages={parser.pages}")

# Navigation order is intentionally not a contract. All five functional
# pages must exist exactly once and each tab must map to a page.
if len(parser.tabs) != 5 or set(parser.tabs) != {"connect", "settings", "deploy", "route", "logs"}:
    raise SystemExit(f"unexpected CSQTT tab set: {parser.tabs}")

# Keep the browser port on the native CSQTT brand palette and floating-tab
# visual language; do not drift back to the earlier generic blue-gray mock.
for token in ('--bg:#fdfdfe', '--surface2:#f2f2f4', '--blue:#1a73e8', '--bg:#09090a', '--surface:#121214', '--blue:#1565d8', 'id="themeMode"', "localStorage.setItem(THEME_KEY,mode)",
              "--blue2:#1565d8", "border-radius:34px", "border-radius:40px",
              "backdrop-filter:blur(18px)", "max-width:760px", "border-radius:999px",
              "width:min(720px,calc(100% - 24px))",
              "<svg viewBox=\"0 0 24 24\" aria-hidden=\"true\">"):
    if token not in html:
        raise SystemExit("native CSQTT visual token missing: " + token)

# Keep key surfaces theme-driven in both light and dark modes; fixed dark
# console/toast surfaces and light-only connected-state gradients are regressions.
for token in (
    "--console-bg:#0c1119", "--console-bg:#080b10",
    "--power-on-shadow:0 12px 28px", "--nav-shadow:0 6px 22px",
    "--card-shadow:0 5px 20px", "--overlay-shadow:0 20px 70px",
    "--toast-bg:#111824", "--toast-bg:#202024",
    ".power.on{background:var(--power-on-bg);color:var(--green);border-color:var(--power-on-border)}",
    ".console{white-space:pre-wrap;overflow-wrap:anywhere;background:var(--console-bg);color:var(--console-text);",
):
    if token not in html:
        raise SystemExit("theme-aware surface token missing: " + token)
if "background:linear-gradient(145deg,#ddfff0,#fff)" in html:
    raise SystemExit("connected power button uses a light-only hardcoded gradient")

# CSQTT 2.5.0 visual adaptation: retain the native five-tab navigation while
# using the newer Material-style surfaces and outlined controls.
for token in (
    "CSQTT 2.5.0 visual adaptation",
    "--blue:#1e73e8",
    "border-radius:32px",
    "border:2px solid #92949b",
    "width:min(900px,calc(100% - 34px))",
    "v2.1.9",
    "CSQTT · NanoPi ARM64",
    "Механизм LaLune используется только для автоматического получения VK-токена.",
    "width:390px;min-width:390px;max-width:390px",
):
    if token not in html:
        raise SystemExit("CSQTT 2.5.0 visual token missing: " + token)

# Preserve CSQTT's two independent authentication selectors. The core accepts
# legacy/vkcalls/auto_js for credential acquisition; LaLune captchaMode remains
# a separate automatic/manual challenge policy.
for token in (
    'id="vkAuthMode"',
    '<option value="legacy">Капча</option>',
    '<option value="vkcalls">Авто</option>',
    '<option value="auto_js">Авто ВК</option>',
    "set('vkAuthMode',s.vkAuthMode||'vkcalls')",
    "s.vkAuthMode=$('vkAuthMode').value",
):
    if token not in html:
        raise SystemExit("CSQTT credential-mode contract missing: " + token)

# The Route tab is intentionally Direct-domain-only; old IP/CIDR controls and
# payload serialization must not return.
route_html = html.split('id="page-route"', 1)[1].split("</section>", 1)[0]
if 'id="directIPs"' in html or "s.directIPs=" in js or "Маршрутизация IP-адресов" in route_html:
    raise SystemExit("Route tab must contain Direct domains only, without IP/CIDR rules")
if 'id="directDomains"' not in route_html:
    raise SystemExit("Route tab is missing the Direct domain list")

# Accessibility contract: navigation state is exposed to assistive technology,
# focus is visible, live updates are announced, and mobile safe areas are respected.
for token in (
    'role="status" aria-live="polite"',
    'aria-live="polite" aria-atomic="true"',
    ':focus-visible{outline:3px solid var(--blue)',
    'env(safe-area-inset-bottom,0px)',
    '@media(prefers-reduced-motion:reduce)',
    "x.setAttribute('aria-current','page')",
    "$('power').setAttribute('aria-pressed',String(connected))",
):
    if token not in html:
        raise SystemExit("accessibility/mobile token missing: " + token)

# The original Android screen uses a 720dp content cap and a floating bottom
# navigation bar; desktop must not switch to a different top-tab/dashboard layout.
if re.search(r'@media\s*\(min-width:\s*980px\)', html):
    raise SystemExit("panel has a desktop-only layout that diverges from native CSQTT")


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

# renderStatus must not overwrite refreshAll() partial-failure diagnostics.
# Catch browser-script syntax regressions that static route/button checks cannot see.
if not re.search(r"async\s+function\s+refreshInfo\s*\(\)", js):
    raise SystemExit("refreshInfo uses await and must be declared async")

if "function renderStatus(){" not in js or "function fillSettings(){" not in js:
    raise SystemExit("renderStatus function could not be isolated for API-status regression check")
render_status = js.split("function renderStatus(){", 1)[1].split("function fillSettings(){", 1)[0]
if "apiStatus" in render_status:
    raise SystemExit("renderStatus overwrites API health indicator set by refreshAll")

# Do not submit an empty CAPTCHA response; backend rejects it by contract.
if "if(!answer){toast('Введите ответ CAPTCHA или откройте страницу проверки VK',true);return}" not in js:
    raise SystemExit("CAPTCHA form does not validate an empty answer before calling the backend")

# Deployment failures may be logged with different English capitalization.
if "state.deployLog.toLowerCase().includes('error')" not in js:
    raise SystemExit("deployment error status is case-sensitive")

# The panel deploys the isolated LaLune-namespaced service, not the stock
# upstream installer; do not assert guessed legacy port numbers in the UI.
if "Это не штатная установка оригинального CSQTT" not in html:
    raise SystemExit("deploy tab does not distinguish the isolated fork from stock CSQTT")
if "Оригинальный CSQTT на 46000/46002" in html:
    raise SystemExit("deploy tab contains an unverified claim about original CSQTT ports")

# Polling every 1.6 seconds fans out to multiple API endpoints and needlessly
# loads the ARM64 gateway; poll at a calmer cadence and pause in hidden tabs.
if "setInterval(()=>{if(!document.hidden)refreshAll()},5000)" not in js:
    raise SystemExit("panel polling must pause while hidden and use a 5-second interval")

# Deployment completion is derived from the backend log, so a reload keeps the result visible.
if "const done=state.deployLogAvailable&&!busy&&state.deployLog.includes('CSQTT_LALUNE_DEPLOY_OK')" not in js:
    raise SystemExit("deployment completion must come from an available backend log and active status")
if "state.statusAvailable=false" not in js or "Статус недоступен" not in js:
    raise SystemExit("VPN status API failure can be misreported as disconnected")
if "state.deployStatusAvailable=false" not in js or "Не удалось получить состояние деплоя" not in js:
    raise SystemExit("deployment status API failure is not represented explicitly")

# Verify each independently fetched backend response updates its own UI state;
# a single failing endpoint must not discard successful responses from others.
for contract in (
    "if('configs'in data)state.configs",
    "if('selected'in data)state.selected",
    "if('settings'in data){state.settings",
    "if('status'in data){state.vpnStatus",
    "if('vk'in data)state.vk",
    "if('captcha'in data)state.captcha",
    "if('deployStatus'in data){state.deploying",
    "if('deployLog'in data){state.deployLog",
    "if('logs'in data)state.logs",
    "if('version'in data)state.version",
    "if(name==='settings')refreshInfo()",
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
