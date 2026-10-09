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


# CSQTT must use the official v2.1.9 deploy.sh protocol, not the generic
# LaLune installer. Secrets arrive in a short-lived mode-0600 file, never argv.
replace_once(
    main,
    "    pub local_binary_dir: Option<String>,",
    "    pub local_binary_dir: Option<String>,\\n\\n    /// One-shot local file containing tunnel/web credentials.\\n    #[arg(long)]\\n    pub secrets_file: Option<String>,",
)
replace_once(
    main,
    "    pub listen_port: Option<u16>,",
    "    pub listen_port: Option<u16>,\\n\\n    /// Install official CSQTT into Docker rather than systemd.\\n    #[arg(long, default_value_t = false)]\\n    pub install_in_docker: bool,",
)
replace_once(
    protocol,
    "            Protocol::Csqtt => (47000, 47002, 1080),",
    "            Protocol::Csqtt => (46000, 46002, 0),",
)
replace_once(
    deploy,
    "use std::process::Command;",
    "use std::process::Command;\\nuse std::fs;\\nuse std::path::Path;\\nuse std::time::{SystemTime, UNIX_EPOCH};",
)
replace_once(
    deploy,
    "pub fn deploy(args: &DeployArgs, proto: Protocol, ports: &Ports) -> Result<()> {\\n    let remote =",
    "pub fn deploy(args: &DeployArgs, proto: Protocol, ports: &Ports) -> Result<()> {\\n    if proto == Protocol::Csqtt {\\n        return deploy_official_csqtt(args, ports);\\n    }\\n    let remote =",
)
official = r'''fn deploy_official_csqtt(args: &DeployArgs, ports: &Ports) -> Result<()> {
    let secrets_path = args.secrets_file.as_deref()
        .ok_or_else(|| anyhow::anyhow!("CSQTT requires the one-shot secrets file"))?;
    let secret_text = fs::read_to_string(secrets_path).context("read CSQTT deployment secrets")?;
    let _ = fs::remove_file(secrets_path);
    let mut secret_lines = secret_text.lines();
    let main_password = secret_lines.next().unwrap_or("").trim();
    let web_user = secret_lines.next().unwrap_or("").trim();
    let web_password = secret_lines.next().unwrap_or("").trim();
    let valid = |s: &str| !s.is_empty() && s.bytes().all(|b| b.is_ascii_alphanumeric());
    if !valid(main_password) || !valid(web_user) || !valid(web_password) {
        anyhow::bail!("tunnel password and web credentials must contain only Latin letters and digits");
    }

    let source = args.local_binary_dir.as_deref()
        .ok_or_else(|| anyhow::anyhow!("official CSQTT assets are not bundled"))?;
    let source = Path::new(source);
    for name in ["deploy.sh", "csqtt-linux-arm64", "csqtt-linux-amd64", "csqtt-linux-armv7"] {
        if !source.join(name).is_file() {
            anyhow::bail!("required official CSQTT 2.1.9 asset is missing: {}", source.join(name).display());
        }
    }

    let nonce = SystemTime::now().duration_since(UNIX_EPOCH)?.as_nanos();
    let bundle_name = format!("csqtt-bundle-{}-{nonce:x}", std::process::id());
    let bundle = std::env::temp_dir().join(&bundle_name);
    fs::create_dir(&bundle).context("create temporary CSQTT bundle")?;
    let result = (|| -> Result<()> {
        for name in ["deploy.sh", "csqtt-linux-arm64", "csqtt-linux-amd64", "csqtt-linux-armv7"] {
            fs::copy(source.join(name), bundle.join(name))
                .with_context(|| format!("stage official asset {name}"))?;
        }
        fs::write(
            bundle.join("csqtt.env"),
            format!("CSQTT_WEB_USER={web_user}
CSQTT_WEB_PASS={web_password}
"),
        ).context("write temporary CSQTT web credentials")?;
        let device_id = format!("{:016x}{:016x}", nonce, std::process::id() as u128);
        fs::write(
            bundle.join("csqtt-deploy.json"),
            format!("{{"main_password":"{main_password}","device_id":"{device_id}"}}
"),
        ).context("write temporary CSQTT deployment overrides")?;

        let remote = format!("{}@{}", args.user, args.host);
        let remote_stage = format!("/tmp/lalune-csqtt-deploy-{}", std::process::id());
        let prepare = format!("set -e; mkdir -p -- '{remote_stage}'; chmod 700 -- '{remote_stage}'");
        let prepared = run_ssh(args, &remote, &prepare).context("prepare remote CSQTT staging directory")?;
        if !prepared.status.success() {
            anyhow::bail!("could not prepare remote CSQTT staging directory: {}", String::from_utf8_lossy(&prepared.stderr));
        }
        if let Err(error) = run_scp(args, &remote, bundle.to_str().unwrap_or(""), &remote_stage) {
            let _ = run_ssh(args, &remote, &format!("rm -rf -- '{remote_stage}'"));
            return Err(error).context("upload official CSQTT installer and credentials");
        }

        let remote_bundle = format!("{remote_stage}/{bundle_name}");
        let peer_port = ports.core.unwrap_or(46000);
        let web_port = ports.warp.unwrap_or(46002);
        let mode = if args.install_in_docker { "docker" } else { "systemd" };
        let script = format!(r#"set -Eeuo pipefail
STAGE='{remote_stage}'
BUNDLE='{remote_bundle}'
cleanup() {{
  rm -rf -- "$STAGE"
  rm -f -- /tmp/deploy.sh /tmp/.csqtt-upload-server /tmp/.csqtt-upload-web.env /tmp/.csqtt-upload-overrides.json
}}
trap cleanup EXIT
case "$(uname -m)" in
  x86_64|amd64) ARCH=amd64 ;;
  aarch64|arm64) ARCH=arm64 ;;
  armv7l|armv7|armhf) ARCH=armv7 ;;
  *) echo "Unsupported server architecture: $(uname -m)" >&2; exit 2 ;;
esac
install -m 0755 "$BUNDLE/deploy.sh" /tmp/deploy.sh
install -m 0755 "$BUNDLE/csqtt-linux-$ARCH" /tmp/.csqtt-upload-server
install -m 0600 "$BUNDLE/csqtt.env" /tmp/.csqtt-upload-web.env
install -m 0600 "$BUNDLE/csqtt-deploy.json" /tmp/.csqtt-upload-overrides.json
env CSQTT_PEER_PORT={peer_port} CSQTT_SSH_PORT={ssh_port} CSQTT_WEB_PORT={web_port} CSQTT_DEPLOY_MODE={mode} bash /tmp/deploy.sh install
"#, ssh_port=args.ssh_port, peer_port=peer_port, web_port=web_port, mode=mode);
        let output = run_ssh(args, &remote, &script).context("run official CSQTT 2.1.9 installer")?;
        let stdout = String::from_utf8_lossy(&output.stdout);
        let stderr = String::from_utf8_lossy(&output.stderr);
        for line in stdout.lines() { println!("[remote] {line}"); }
        for line in stderr.lines() { eprintln!("[remote:err] {line}"); }
        if !output.status.success() || !stdout.lines().any(|line| line.trim() == "CSQTT_DEPLOY_OK") {
            anyhow::bail!("official CSQTT installer failed (exit {}); see remote output above", output.status);
        }
        println!("[deploy] official CSQTT 2.1.9 deployment completed");
        Ok(())
    })();
    let _ = fs::remove_dir_all(&bundle);
    result
}

'''
replace_once(deploy, "fn write_askpass_helper() -> Result<std::path::PathBuf> {", official + "fn write_askpass_helper() -> Result<std::path::PathBuf> {")


# Preserve the CSQTT 2.1.9 authorization dialog contract in the native API:
# credentials are sent to DeployManager through a short-lived 0600 file.
deploy_go = ROOT / "Desktop/Libs/deploy.go"
replace_once(
    deploy_go,
    '\\tListenPort  int    `json:"listenPort"`',
    '\\tListenPort  int    `json:"listenPort"`\\n\\tMainPassword string `json:"mainPassword"`\\n\\tWebUser string `json:"webUser"`\\n\\tWebPassword string `json:"webPassword"`\\n\\tDockerInstall bool `json:"dockerInstall"`\n\tUninstall bool `json:"uninstall"`',
)
replace_once(
    deploy_go,
    '\\tif strings.TrimSpace(req.Host) == "" {',
    '\\tif strings.EqualFold(strings.TrimSpace(req.Protocol), "CSQTT") {\\n\\t\\tif !validCSQTTSecret(req.MainPassword) || !validCSQTTSecret(req.WebUser) || !validCSQTTSecret(req.WebPassword) {\\n\\t\\t\\tdeployAppend("[deploy] CSQTT: задайте пароль туннеля, логин и пароль WEB только латиницей и цифрами")\\n\\t\\t\\treturn false\\n\\t\\t}\\n\\t}\\n\\tif strings.TrimSpace(req.Host) == "" {',
)
replace_once(
    deploy_go,
    'func DeployProtocol(reqJSON string) bool {',
    'func validCSQTTSecret(value string) bool {\\n\\tif value == "" { return false }\\n\\tfor _, r := range value { if !((r >= \'a\' && r <= \'z\') || (r >= \'A\' && r <= \'Z\') || (r >= \'0\' && r <= \'9\')) { return false } }\\n\\treturn true\\n}\\n\\nfunc DeployProtocol(reqJSON string) bool {',
)
replace_once(
    deploy_go,
    '\\tif req.SSHPort > 0 {',
    '''\\tsecretsFile := ""
\\tif strings.EqualFold(strings.TrimSpace(req.Protocol), "CSQTT") && !req.Uninstall {
\\t\\tf, err := os.CreateTemp("", "csqtt-deploy-secrets-*.txt")
\\t\\tif err != nil { deployAppend("[deploy] не удалось создать временный файл авторизации"); return false }
\\t\\t_ = f.Chmod(0600)
\\t\\t_, writeErr := f.WriteString(req.MainPassword + "\\n" + req.WebUser + "\\n" + req.WebPassword + "\\n")
\\t\\tcloseErr := f.Close()
\\t\\tif writeErr != nil || closeErr != nil { _ = os.Remove(f.Name()); deployAppend("[deploy] не удалось сохранить временные данные авторизации"); return false }
\\t\\tsecretsFile = f.Name()
\\t\\targs = append(args, "--secrets-file", secretsFile)
\\t\\tif req.DockerInstall { args = append(args, "--install-in-docker") }\n\t\t
\\t}
\\tif req.Uninstall { args = append(args, "--uninstall") }\n\tif req.SSHPort > 0 {''',
)
replace_once(
    deploy_go,
    '\\tif err != nil {\\n\\t\\tdeployAppend("[deploy] ошибка запуска: " + err.Error())\\n\\t\\treturn false\\n\\t}\\n\\tstderr, err := cmd.StderrPipe()',
    '\\tif err != nil {\\n\\t\\tif secretsFile != "" { _ = os.Remove(secretsFile) }\\n\\t\\tdeployAppend("[deploy] ошибка запуска: " + err.Error())\\n\\t\\treturn false\\n\\t}\\n\\tstderr, err := cmd.StderrPipe()',
)
replace_once(
    deploy_go,
    '\\tif err != nil {\\n\\t\\tdeployAppend("[deploy] ошибка запуска: " + err.Error())\\n\\t\\treturn false\\n\\t}\\n\\n\\tif err := cmd.Start(); err != nil {',
    '\\tif err != nil {\\n\\t\\tif secretsFile != "" { _ = os.Remove(secretsFile) }\\n\\t\\tdeployAppend("[deploy] ошибка запуска: " + err.Error())\\n\\t\\treturn false\\n\\t}\\n\\n\\tif err := cmd.Start(); err != nil {',
)
replace_once(
    deploy_go,
    '\\tif err := cmd.Start(); err != nil {\\n\\t\\tdeployAppend("[deploy] не удалось запустить DeployManager: " + err.Error())',
    '\\tif err := cmd.Start(); err != nil {\\n\\t\\tif secretsFile != "" { _ = os.Remove(secretsFile) }\\n\\t\\tdeployAppend("[deploy] не удалось запустить DeployManager: " + err.Error())',
)
replace_once(
    deploy_go,
    '\\t\\terr := cmd.Wait()\\n\\t\\tif err != nil {',
    '\\t\\terr := cmd.Wait()\\n\\t\\tif secretsFile != "" { _ = os.Remove(secretsFile) }\\n\\t\\tif err != nil {',
)


replace_once(
    main,
    "    pub install_in_docker: bool,",
    "    pub install_in_docker: bool,\\n\\n    /// Uninstall the official CSQTT runtime while preserving its database.\\n    #[arg(long, default_value_t = false)]\\n    pub uninstall: bool,",
)
replace_once(
    deploy,
    "fn deploy_official_csqtt(args: &DeployArgs, ports: &Ports) -> Result<()> {",
    "fn deploy_official_csqtt(args: &DeployArgs, ports: &Ports) -> Result<()> {\\n    if args.uninstall { return uninstall_official_csqtt(args, ports); }",
)
uninstall = r'''fn uninstall_official_csqtt(args: &DeployArgs, ports: &Ports) -> Result<()> {
    let source = args.local_binary_dir.as_deref()
        .ok_or_else(|| anyhow::anyhow!("official CSQTT assets are not bundled"))?;
    let source = Path::new(source).join("deploy.sh");
    if !source.is_file() { anyhow::bail!("official CSQTT 2.1.9 deploy.sh is missing"); }
    let nonce = SystemTime::now().duration_since(UNIX_EPOCH)?.as_nanos();
    let bundle_name = format!("csqtt-uninstall-{}-{nonce:x}", std::process::id());
    let bundle = std::env::temp_dir().join(&bundle_name);
    fs::create_dir(&bundle).context("create temporary CSQTT uninstall bundle")?;
    let result = (|| -> Result<()> {
        fs::copy(source, bundle.join("deploy.sh")).context("stage official CSQTT uninstall script")?;
        let remote = format!("{}@{}", args.user, args.host);
        let remote_stage = format!("/tmp/lalune-csqtt-uninstall-{}", std::process::id());
        let prepare = format!("set -e; mkdir -p -- '{remote_stage}'; chmod 700 -- '{remote_stage}'");
        let prepared = run_ssh(args, &remote, &prepare).context("prepare remote uninstall staging directory")?;
        if !prepared.status.success() {
            anyhow::bail!("could not prepare remote CSQTT uninstall staging directory: {}", String::from_utf8_lossy(&prepared.stderr));
        }
        if let Err(error) = run_scp(args, &remote, bundle.to_str().unwrap_or(""), &remote_stage) {
            let _ = run_ssh(args, &remote, &format!("rm -rf -- '{remote_stage}'"));
            return Err(error).context("upload official CSQTT uninstall script");
        }
        let remote_bundle = format!("{remote_stage}/{bundle_name}");
        let script = format!(r#"set -Eeuo pipefail
STAGE='{remote_stage}'
trap 'rm -rf -- "$STAGE"; rm -f -- /tmp/deploy.sh' EXIT
install -m 0755 '{remote_bundle}/deploy.sh' /tmp/deploy.sh
env CSQTT_PEER_PORT={peer_port} CSQTT_SSH_PORT={ssh_port} CSQTT_WEB_PORT={web_port} bash /tmp/deploy.sh uninstall
echo CSQTT_UNINSTALL_OK
"#, ssh_port=args.ssh_port, peer_port=ports.core.unwrap_or(46000), web_port=ports.warp.unwrap_or(46002));
        let output = run_ssh(args, &remote, &script).context("run official CSQTT uninstall")?;
        let stdout = String::from_utf8_lossy(&output.stdout);
        let stderr = String::from_utf8_lossy(&output.stderr);
        for line in stdout.lines() { println!("[remote] {line}"); }
        for line in stderr.lines() { eprintln!("[remote:err] {line}"); }
        if !output.status.success() || !stdout.lines().any(|line| line.trim() == "CSQTT_UNINSTALL_OK") {
            anyhow::bail!("official CSQTT uninstall failed (exit {})", output.status);
        }
        println!("[deploy] official CSQTT uninstall completed");
        Ok(())
    })();
    let _ = fs::remove_dir_all(&bundle);
    result
}

'''
replace_once(deploy, "fn deploy_official_csqtt(args: &DeployArgs, ports: &Ports) -> Result<()> {", uninstall + "fn deploy_official_csqtt(args: &DeployArgs, ports: &Ports) -> Result<()> {")

print("CSQTT DeployManager adaptation applied")
