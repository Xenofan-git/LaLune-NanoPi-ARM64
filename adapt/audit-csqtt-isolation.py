#!/usr/bin/env python3
"""Audit the pinned CSQTT 2.1.9 hazards and the namespaced LaLune deploy flow.

The Deploy button uses deploy-csqtt-lalune.sh, generated from the pinned
upstream deploy.sh by the dedicated patcher. Legacy install/uninstall scripts
are test fixtures only and must not be wired into DeployManager.
"""
from pathlib import Path
import sys

deploy = Path("server-assets/deploy.sh")
net_setup = Path("server-source/rust-server/net_setup.rs")
tun_device = Path("server-source/rust-server/tun_device.rs")
if not deploy.is_file() or not net_setup.is_file() or not tun_device.is_file():
    raise SystemExit("required pinned CSQTT source files missing; refusing to skip isolation audit")

script = deploy.read_text()
net = net_setup.read_text()
tun = tun_device.read_text()

required_global_hazards = [
    'readonly CSQTT_IFACE="csqtt1"',
    'readonly CSQTT_CONFIG_DIR="/etc/csqtt"',
    'readonly CSQTT_SYSCTL_FILE="/etc/sysctl.d/99-csqtt.conf"',
    'readonly CSQTT_DOCKER_CONTAINER="csqtt"',
    'readonly CSQTT_LE_SERVICE="csqtt-letsencrypt.service"',
]
for marker in required_global_hazards:
    if marker not in script:
        raise SystemExit(f"upstream hazard marker changed; manual re-audit required: {marker}")

if 'pub const TUN_IFACE: &str = "csqtt1";' not in net:
    raise SystemExit("net_setup.rs TUN constant changed; manual re-audit required")
if 'pub const TUN_IFACE: &str = "csqtt1";' not in tun:
    raise SystemExit("tun_device.rs TUN constant changed; manual re-audit required")
if 'pub const TUN_SUBNET: &str = "10.66.67.0/24";' not in tun:
    raise SystemExit("tun subnet changed; manual re-audit required")

deploy_rs = Path("upstream-lalune/Core/DeployManager/src/deploy.rs")
if not deploy_rs.is_file():
    raise SystemExit("patched DeployManager source missing")
patched = deploy_rs.read_text()
if "CSQTT_ISOLATION_REQUIRED" in patched or "exit 73" in patched:
    raise SystemExit("obsolete fail-closed stub remains instead of the original-derived LaLune deploy flow")
if "install-csqtt-lalune.sh" in patched or "uninstall-csqtt-lalune.sh" in patched:
    raise SystemExit("legacy fixture installer must not be wired into DeployManager")
for marker in (
    "deploy-csqtt-lalune.sh",
    "CSQTT_DEPLOY_STAGE",
    "CSQTT_LALUNE_DEPLOY_OK",
    "CSQTT_LALUNE_UNINSTALL_OK",
    "fn deploy_official_csqtt",
):
    if marker not in patched:
        raise SystemExit(f"isolated deployment marker missing: {marker}")
if "bash /tmp/deploy.sh uninstall" in patched or "deploy.sh uninstall" in patched:
    raise SystemExit("unsafe upstream uninstaller invocation found")

print("CSQTT isolation audit passed: upstream hazards detected and only namespaced LaLune installer/uninstaller are wired.")
