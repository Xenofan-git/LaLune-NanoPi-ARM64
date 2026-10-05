#!/usr/bin/env bash
set -euo pipefail

SRC="${1:-upstream-lalune}"
FRONTEND="$SRC/Frontend"

python3 - "$FRONTEND" <<'PY'
from pathlib import Path
import sys

root = Path(sys.argv[1])

# Flutter web cannot import dart:io. The watchdog only needs Platform on
# Android/iOS, while web must never try to restart a native backend.
p = root / "lib/backend_watchdog.dart"
s = p.read_text()
s = s.replace("import 'dart:io' show Platform;\n", "")
s = s.replace("    if (!(Platform.isAndroid || Platform.isIOS)) return;\n", "")
p.write_text(s)

# On web the UI is served from the NanoPi itself. Use same-origin /api/*
# so the browser never needs CORS access to port 1062.
p = root / "lib/api/api_client.dart"
s = p.read_text()
s = s.replace("import 'package:http/http.dart' as http;\n",
              "import 'package:flutter/foundation.dart' show kIsWeb;\nimport 'package:http/http.dart' as http;\n")
old = """  Uri _uri(String path, [Map<String, String>? query]) {
    return Uri(
      scheme: 'http',
      host: _host,
      port: _port,
      path: path,
      queryParameters: query,
    );
  }"""
new = """  Uri _uri(String path, [Map<String, String>? query]) {
    if (kIsWeb && _host == _defaultHost) {
      final base = Uri.base;
      final clean = path.startsWith('/') ? path.substring(1) : path;
      return base.replace(
        path: '/api/$clean',
        queryParameters: query,
      );
    }
    return Uri(
      scheme: 'http',
      host: _host,
      port: _port,
      path: path,
      queryParameters: query,
    );
  }"""
if old not in s:
    raise SystemExit("ApiClient _uri block not found")
s = s.replace(old, new)
p.write_text(s)

# Browser cannot reliably scan arbitrary LAN IPs. Keep manual router
# management in the original UI, but make scanning a harmless no-op on web.
p = root / "lib/state/router_scanner.dart"
s = p.read_text()
s = s.replace("import 'dart:async';\n",
              "import 'dart:async';\nimport 'package:flutter/foundation.dart' show kIsWeb;\n")
needle = """  static Stream<RouterInfo> scan({
    Duration timeout = const Duration(milliseconds: 600),"""
repl = """  static Stream<RouterInfo> scan({
    Duration timeout = const Duration(milliseconds: 600),"""
# Inject early return after the opening method body.
marker = "  }) async* {\n"
if marker not in s:
    raise SystemExit("RouterScanner scan marker not found")
s = s.replace(marker, "  }) async* {\n    if (kIsWeb) return;\n", 1)
p.write_text(s)
PY

cd "$FRONTEND"
flutter pub get
flutter build web --release
