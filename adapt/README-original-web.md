# Original LaLune Web UI for NanoPi

Browser -> nginx:18788 -> /api/* -> original LaLune backend 127.0.0.1:1062

The original Flutter screens and API remain intact. The adaptation only removes browser-hosting incompatibilities, uses same-origin /api/* requests, disables LAN auto-scan in a browser, and builds the original frontend with Flutter Web. The original ARM64 backend remains separate.
