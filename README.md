# LaLune-NanoPi-ARM64

ARM64 build and NanoPi integration for LaLune.

## Upstream

Builds are based on upstream Endlad2/LaLune, pinned to commit e4a6d08.

## Target

- NanoPi R3S LTS
- Debian ARM64
- Linux ARM64
- Isolated LaLune/CSQTT tunnel path
- Keenetic-selectable connection without replacing the existing 3x-ui path

The first stage validates a native ARM64 desktop build. Network/gateway integration is intentionally kept separate from the existing 3x-ui, Tailscale, CSQTT and HydraRoute configurations.

## Build

GitHub Actions uses the public ARM64 runner ubuntu-24.04-arm.

The build workflow checks out the pinned upstream source, prepares the Flutter web frontend, and produces a Linux ARM64 artifact.