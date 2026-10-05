#!/usr/bin/env bash
set -euo pipefail

SRC="${1:-upstream-lalune}"
FRONTEND="$SRC/Frontend"

python3 - "$FRONTEND" <<'PY'
from pathlib import Path
import sys

root = Path(sys.argv[1])

p = root / "lib/backend_watchdog.dart"
s = p.read_text().replace("import 'dart:io' show Platform;\n", "")
s = s.replace("    if (!(Platform.isAndroid || Platform.isIOS)) return;\n", "")
p.write_text(s)

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
      final clean = path.startsWith('/') ? path.substring(1) : path;
      return Uri.base.replace(path: '/api/$clean', queryParameters: query);
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
p.write_text(s.replace(old, new))

p = root / "lib/state/router_scanner.dart"
s = p.read_text()
if "import 'package:flutter/foundation.dart' show kIsWeb;" not in s:
    s = s.replace("import 'dart:async';\n",
                  "import 'dart:async';\nimport 'package:flutter/foundation.dart' show kIsWeb;\n", 1)
marker = "  }) async* {\n"
if marker not in s:
    raise SystemExit("RouterScanner scan marker not found")
if "if (kIsWeb) return;" not in s:
    s = s.replace(marker, "  }) async* {\n    if (kIsWeb) return;\n", 1)
p.write_text(s)
PY

if [ -d "$SRC/Assets" ]; then
  rm -rf "$FRONTEND/assets"
  cp -a "$SRC/Assets" "$FRONTEND/assets"
fi

cd "$FRONTEND"
flutter create . --platforms web
flutter pub get
flutter build web --release
