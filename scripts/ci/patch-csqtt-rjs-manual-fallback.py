#!/usr/bin/env python3
"""Patch the pinned CSQTT client in disposable builds so RJS reaches Linux manual CAPTCHA.

This patch is intentionally applied only to a source checkout pinned by CI. It does
not modify upstream or any running device. The Linux panel can service the manual
mode event and the 60-second result wait; it cannot service WBV Auto's 10-second
wait because no WebView solver is available on Linux.
"""
from pathlib import Path

path = Path("client-source/rust-client/captcha.rs")
source = path.read_text(encoding="utf-8")

old = '''                        crate::log_error!(
                            "[STREAM {stream_id}] [КАПЧА] RJS: ошибка, fallback на WBV Auto: {error}"
                        );
                        self.webview(stream_id, captcha, "auto", Duration::from_secs(10))
                            .await'''
new = '''                        crate::log_error!(
                            "[STREAM {stream_id}] [КАПЧА] RJS: ошибка, fallback на ручную CAPTCHA: {error}"
                        );
                        self.webview(stream_id, captcha, "manual", Duration::from_secs(60))
                            .await'''

count = source.count(old)
if count != 1:
    raise SystemExit(f"RJS manual fallback: expected one source match, found {count}")

patched = source.replace(old, new, 1)
if 'self.webview(stream_id, captcha, "manual", Duration::from_secs(60))' not in patched:
    raise SystemExit("RJS manual fallback was not installed")
if 'RJS: ошибка, fallback на WBV Auto' in patched:
    raise SystemExit("stale RJS Auto fallback remains")

path.write_text(patched, encoding="utf-8")
print("CSQTT_RJS_MANUAL_FALLBACK_PATCH_PASS")
