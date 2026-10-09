#!/usr/bin/env python3
"""Patch pinned LaLune DeployManager to stage the bundled CSQTT 2.1.9 asset safely.

Run after apply-pinned-original-linux-arm64-policy.py, against the pinned upstream
source checkout. This is source adaptation only; it does not deploy to any server.
"""
from pathlib import Path

ROOT = Path("upstream-lalune")

def replace_once(path: Path, old: str, new: str) -> None:
    source = path.read_text()
    count = source.count(old)
    if count != 1:
        raise SystemExit(f"expected one marker in {path}, found {count}: {old[:100]!r}")
    path.write_text(source.replace(old, new, 1))

main = ROOT / "Core/DeployManager/src/main.rs"
replace_once(
    main,
    "    pub listen_port: Option<u16>,",
    "    pub listen_port: Option<u16>,\n\n    /// Local directory containing the bundled CSQTT server assets.\n    #[arg(long)]\n    pub local_binary_dir: Option<String>,",
)

protocol = ROOT / "Core/DeployManager/src/protocol.rs"
replace_once(protocol, '            Protocol::Csqtt => "csqtt-core",', '            Protocol::Csqtt => "csqtt-lalune",')
replace_once(protocol, "            Protocol::Csqtt => (443, 0, 1080),", "            Protocol::Csqtt => (47000, 47002, 1080),")

deploy = ROOT / "Core/DeployManager/src/deploy.rs"
replace_once(
    deploy,
    "    let script = install_script(proto, ports);",
    '''    // Stage bundled CSQTT assets in a unique temporary directory. The target is
    // prepared over SSH first so scp has deterministic directory semantics.
    let remote_tmp = format!("/tmp/lalune-deploy-{}", std::process::id());
    let has_local_csqtt = proto == Protocol::Csqtt && args.local_binary_dir.is_some();
    if has_local_csqtt {
        let prepare = format!("set -e\\nmkdir -p -- '{remote_tmp}'\\nchmod 700 -- '{remote_tmp}'\\n");
        let prepared = run_ssh(args, &remote, &prepare)?;
        if !prepared.status.success() {
            anyhow::bail!("could not prepare remote staging directory: {}", String::from_utf8_lossy(&prepared.stderr));
        }
        let local_dir = args.local_binary_dir.as_deref().expect("checked above");
        if let Err(error) = run_scp(args, &remote, local_dir, &remote_tmp) {
            let cleanup = format!("rm -rf -- '{remote_tmp}'\\n");
            let _ = run_ssh(args, &remote, &cleanup);
            return Err(error);
        }
    }
    let local_dir = if has_local_csqtt { Some(remote_tmp.as_str()) } else { None };
    let script = install_script(proto, ports, local_dir);''',
)

run_ssh_marker = "fn run_ssh(args: &DeployArgs, remote: &str, script: &str) -> Result<std::process::Output> {"
run_scp = '''fn run_scp(args: &DeployArgs, remote: &str, local: &str, remote_stage: &str) -> Result<()> {
    let mut scp_args = vec![
        "-r".to_string(),
        "-o".to_string(),
        "StrictHostKeyChecking=accept-new".to_string(),
        "-o".to_string(),
        "ConnectTimeout=20".to_string(),
        "-P".to_string(),
        args.ssh_port.to_string(),
    ];
    if let Some(key) = &args.key {
        scp_args.push("-i".to_string());
        scp_args.push(key.clone());
    }

    let target = format!("{remote}:{remote_stage}/");
    let mut askpass_env: Option<(std::path::PathBuf, String)> = None;
    let (program, mut command_args) = if args.password.is_some() && have_sshpass() {
        let mut a = vec!["-e".to_string(), "scp".to_string()];
        a.extend(scp_args.clone());
        ("sshpass".to_string(), a)
    } else {
        if let Some(password) = &args.password {
            let helper = write_askpass_helper()?;
            askpass_env = Some((helper, password.clone()));
        }
        ("scp".to_string(), scp_args.clone())
    };
    command_args.push(local.to_string());
    command_args.push(target);

    let mut command = Command::new(&program);
    command.args(&command_args);
    if let Some(password) = &args.password {
        if program == "sshpass" {
            command.env("SSHPASS", password);
        }
    }
    if let Some((helper, password)) = &askpass_env {
        command.env("SSHPASS", password);
        command.env("SSH_ASKPASS", helper);
        command.env("SSH_ASKPASS_REQUIRE", "force");
        if std::env::var_os("DISPLAY").is_none() {
            command.env("DISPLAY", ":0");
        }
    }

    let result = command.output();
    if let Some((helper, _)) = askpass_env {
        let _ = std::fs::remove_file(helper);
    }
    let output = result.context("scp failed to start")?;
    if !output.status.success() {
        anyhow::bail!("scp failed: {}", String::from_utf8_lossy(&output.stderr));
    }
    Ok(())
}

'''
replace_once(deploy, run_ssh_marker, run_scp + run_ssh_marker)
replace_once(
    deploy,
    "fn install_script(proto: Protocol, ports: &Ports) -> String {",
    "fn install_script(proto: Protocol, ports: &Ports, local_dir: Option<&str>) -> String {",
)
replace_once(
    deploy,
    "    let flags = ports.flags();",
    '''    let flags = if proto == Protocol::Csqtt {
        format!(" --listen {} --web-port {} --config-dir /etc/csqtt-lalune", ports.core.unwrap_or(47000), ports.warp.unwrap_or(47002))
    } else {
        ports.flags()
    };
    let local_dir = local_dir.unwrap_or("");''',
)
replace_once(
    deploy,
    'echo "[install] protocol={proto}"',
    '''echo "[install] protocol={proto}"
LOCAL_STAGE="{local_dir}"
if [ -n "$LOCAL_STAGE" ]; then trap 'rm -rf -- "$LOCAL_STAGE"' EXIT; fi''',
)
replace_once(
    deploy,
    'echo "[install] protocol={proto}"',
    r'''echo "[install] protocol={proto}"
LOCAL_STAGE="{local_dir}"
if [ -n "$LOCAL_STAGE" ]; then trap 'rm -rf -- "$LOCAL_STAGE"' EXIT; fi
if [ "{proto}" = "csqtt" ] && systemctl list-unit-files csqtt-47000.service --no-legend 2>/dev/null | grep -q '^csqtt-47000.service'; then
  echo "[install] refusing to overwrite an existing CSQTT service (csqtt-47000.service)" >&2
  exit 1
fi''',
)
start = 'echo "[install] downloading $URL"'
end = 'if command -v systemctl >/dev/null 2>&1; then'
source = deploy.read_text()
if source.count(start) != 1 or source.count(end) != 1:
    raise SystemExit("could not identify unique download/install block in deploy.rs")
a = source.index(start)
b = source.index(end, a)
replacement = '''if [ -n "$LOCAL_STAGE" ] && [ "{proto}" = "csqtt" ]; then
  SOURCE="$LOCAL_STAGE/server-assets/csqtt-linux-$ASSET_ARCH"
  if [ ! -s "$SOURCE" ]; then echo "[install] bundled CSQTT asset missing: $SOURCE" >&2; exit 1; fi
  TMP_DEST="${{DEST}}.new.$$"
  install -m 0755 "$SOURCE" "$TMP_DEST"
  mv -f "$TMP_DEST" "$DEST"
  echo "[install] installed bundled CSQTT asset for $ASSET_ARCH"
else
  echo "[install] downloading $URL"
  TMP_DEST="${{DEST}}.new.$$"
  if command -v curl >/dev/null 2>&1; then
    curl -fSL --retry 3 "$URL" -o "$TMP_DEST"
  elif command -v wget >/dev/null 2>&1; then
    wget -O "$TMP_DEST" "$URL"
  else
    echo "[install] error: neither curl nor wget available" >&2; exit 1
  fi
  if [ ! -s "$TMP_DEST" ]; then echo "[install] error: download empty" >&2; rm -f "$TMP_DEST"; exit 1; fi
  chmod 0755 "$TMP_DEST"
  mv -f "$TMP_DEST" "$DEST"
fi
if [ ! -s "$DEST" ]; then echo "[install] error: installed file is empty" >&2; exit 1; fi
chmod +x "$DEST"
echo "[install] installed $DEST ($(stat -c %s "$DEST" 2>/dev/null || echo '?') bytes)"

'''
source = source[:a] + replacement + source[b:]
deploy.write_text(source)

# Keep the deployed service separate from an existing service of the same core.
replace_once(deploy, 'cat >/etc/systemd/system/{bin}.service <<UNIT', 'cat >/etc/systemd/system/{bin}-deployed.service <<UNIT')
replace_once(deploy, 'systemctl enable {bin}.service', 'systemctl enable {bin}-deployed.service')
replace_once(deploy, 'systemctl restart {bin}.service', 'systemctl restart {bin}-deployed.service')
replace_once(deploy, 'systemctl is-active --quiet {bin}.service', 'systemctl is-active --quiet {bin}-deployed.service')
replace_once(deploy, '{bin}.service failed to start', '{bin}-deployed.service failed to start')
replace_once(deploy, 'status {bin}.service >&2', 'status {bin}-deployed.service >&2')
replace_once(deploy, 'journalctl -u {bin}.service -n 40', 'journalctl -u {bin}-deployed.service -n 40')
replace_once(deploy, 'systemd service {bin}.service started', 'systemd service {bin}-deployed.service started')

print("CSQTT DeployManager adaptation applied")
