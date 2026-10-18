#!/usr/bin/env python3
"""Real Chromium smoke test for the packaged CSQTT panel at mobile/desktop widths.

The backend is deliberately unavailable here: this test exercises the actual
HTML/CSS/JS interaction contract and checks that API failure does not crash UI.
API calls are aborted so no live account, token, server, or network is touched.
"""
from pathlib import Path
from playwright.sync_api import sync_playwright

HTML = Path("adapt/csqtt-panel-preview.html").resolve()
EXPECTED = ["connect", "settings", "deploy", "route", "logs", "info"]
WIDTHS = [320, 360, 390, 768, 1280]


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page_errors = []
        page.on("pageerror", lambda error: page_errors.append(str(error)))
        page.route("**/api/**", lambda route: route.abort())
        page.goto(HTML.as_uri(), wait_until="domcontentloaded")
        page.wait_for_timeout(150)

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
              body: document.body.scrollWidth,
              nav: (() => { const r=document.querySelector('.tabs').getBoundingClientRect();
                return {left:r.left,right:r.right,width:r.width}; })()
            })""")
            assert dimensions["document"] <= width, (
                f"horizontal overflow at {width}px: {dimensions}"
            )
            assert dimensions["nav"]["left"] >= -1 and dimensions["nav"]["right"] <= width + 1, (
                f"bottom navigation escapes viewport at {width}px: {dimensions}"
            )

        # Fixed navigation and dialogs should remain usable after viewport changes.
        page.locator('button[data-page="connect"]').click()
        assert page.locator("#page-connect").is_visible()
        assert not page.locator("#deploySecretsOverlay").is_visible()
        assert not page_errors, f"uncaught browser errors: {page_errors}"
        browser.close()
    print("CSQTT_CHROMIUM_UI_SMOKE_PASS widths=320,360,390,768,1280 tabs=6")


if __name__ == "__main__":
    main()
