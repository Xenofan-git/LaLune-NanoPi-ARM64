# LaLune CSQTT CAPTCHA Bridge

The LaLune NanoPi panel opens the VK Smart CAPTCHA URL in a normal browser tab when the headless CSQTT core emits CAPTCHA_SOLVE.

The optional Manifest V3 bridge runs only on id.vk.com / id.vk.ru, watches the page's captchaNotRobot.check response, extracts response.success_token, and returns it to the waiting LaLune panel as CAPTCHA_RESULT.

## Desktop Chrome / Chromium

1. Open Extensions.
2. Enable Developer mode.
3. Choose Load unpacked.
4. Select this captcha-bridge directory.
5. Open the LaLune panel and connect normally.

The bridge uses MAIN-world injection so it can observe the page's own fetch/XHR calls and is configured for all VK frames.

## Android

Standard Chrome for Android does not provide the desktop extension workflow. Firefox for Android supports add-ons, so it is the preferred mobile browser for this bridge when the add-on is installed through its supported extension mechanism.

## Security

The bridge is restricted to VK identity pages. It does not log or persist CAPTCHA tokens. The LaLune backend accepts a result only while the matching session_token is pending.
