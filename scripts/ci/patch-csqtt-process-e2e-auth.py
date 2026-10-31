#!/usr/bin/env python3
"""Patch the pinned CSQTT client checkout for isolated process-level E2E only.

The patch is applied to a disposable CI clone, never to upstream or production.
Without all three explicit CSQTT_TEST_TURN_* variables the stock VK auth path
is unchanged. Credential values are never logged.
"""
from pathlib import Path
import os

# A TURN allocation can survive a CSQTT server restart, leaving the reader blocked.
# The watchdog is opt-in so a second matrix leg can exercise the stock receive wait.
session_path = Path("client-source/rust-client/session.rs")
session_source = session_path.read_text(encoding="utf-8")
recv_marker = """    async fn recv(&mut self) -> Result<PacketBuf> {
        loop {
            let mut packet = self
                .receiver
                .recv()
                .await
                .context("TURN allocation receive")?;"""
recv_replacement = """    async fn recv(&mut self) -> Result<PacketBuf> {
        // Default is conservative; the isolated E2E lowers this timeout.
        let idle_timeout_ms = std::env::var("CSQTT_TEST_PEER_IDLE_TIMEOUT_MS")
            .ok()
            .and_then(|value| value.parse::<u64>().ok())
            .filter(|value| *value >= 1000)
            .unwrap_or(60_000);
        loop {
            let mut packet = tokio::time::timeout(
                std::time::Duration::from_millis(idle_timeout_ms),
                self.receiver.recv(),
            )
            .await
            .map_err(|_| anyhow::anyhow!("CSQTT peer inactivity timeout after {idle_timeout_ms} ms"))?
            .context("TURN allocation receive")?;"""
path = Path("client-source/rust-client/auth.rs")
source = path.read_text(encoding="utf-8")
marker = '    pub async fn get_credentials(&self, link: &str, stream_id: usize) -> Result<TurnCredentials> {'
if source.count(marker) != 1:
    raise SystemExit("Expected exactly one VkAuth::get_credentials insertion point; refusing patch")

hook = marker + """
        // Isolated process-E2E fixture only. All values must be explicitly
        // supplied by the workflow; normal execution retains the VK auth path.
        if let (Ok(username), Ok(password), Ok(server)) = (
            std::env::var("CSQTT_TEST_TURN_USERNAME"),
            std::env::var("CSQTT_TEST_TURN_PASSWORD"),
            std::env::var("CSQTT_TEST_TURN_SERVER"),
        ) {
            if !username.is_empty() && !password.is_empty() && !server.is_empty() {
                return Ok(TurnCredentials {
                    username: Arc::from(username),
                    password: Arc::from(password),
                    server_addresses: vec![Arc::<str>::from(server)].into(),
                });
            }
        }
"""
path.write_text(source.replace(marker, hook, 1), encoding="utf-8")
if session_source.count(recv_marker) != 1:
    raise SystemExit("Expected exactly one TransportReader::recv insertion point; refusing patch")
watchdog_enabled = os.environ.get("CSQTT_TEST_ENABLE_IDLE_WATCHDOG") == "1"
if watchdog_enabled:
    if session_source.count(recv_marker) != 1:
        raise SystemExit("Expected exactly one TransportReader::recv insertion point; refusing patch")
    session_patched = session_source.replace(recv_marker, recv_replacement, 1)
else:
    session_patched = session_source
    print("PASS: receive-idle watchdog injection disabled; stock TransportReader::recv wait retained.")

# Instrument unsolicited inbound TUNCONF packets in the long-lived reader.
# Reconnect handshakes use the separate register()/ConfigResponse path instrumented
# below; both paths are required to measure recovery accurately.
reader_marker = """        if packet.as_slice().starts_with(b"TUNCONF:") {
            if let Ok(ConfigResponse::Config(config)) = parse_config_response(packet.as_slice()) {
                let _ = config_tx.try_send(config);"""
reader_replacement = """        if packet.as_slice().starts_with(b"TUNCONF:") {
            if let Ok(ConfigResponse::Config(config)) = parse_config_response(packet.as_slice()) {
                if let Ok(path) = std::env::var("CSQTT_TEST_TUNCONF_COUNTER_FILE") {
                    if let Ok(mut file) = std::fs::OpenOptions::new().create(true).append(true).open(path) {
                        let _ = std::io::Write::write_all(&mut file, b"TUNCONF\\n");
                    }
                }
                crate::log_error!("CSQTT_TEST_TUNCONF_PARSED");
                let _ = config_tx.try_send(config);"""
if session_patched.count(reader_marker) != 1:
    raise SystemExit("Expected exactly one client inbound TUNCONF parse branch; refusing instrumentation")
session_patched = session_patched.replace(reader_marker, reader_replacement, 1)

# Worker reconnects receive their configuration in register()/handshake before
# the long-lived reader loop is started. Count that path separately: it is the
# expected path during same-process recovery.
handshake_marker = """                if let Some(sender) = &config_tx {
                    let _ = sender.try_send(value);
                }
                crate::log_error!("[ВОРКЕР #{}] Конфиг получен", config.id);"""
handshake_replacement = """                if value.starts_with("TUNCONF:") {
                    if let Ok(path) = std::env::var("CSQTT_TEST_TUNCONF_COUNTER_FILE") {
                        if let Ok(mut file) = std::fs::OpenOptions::new().create(true).append(true).open(path) {
                            let _ = std::io::Write::write_all(&mut file, b"TUNCONF_HANDSHAKE\\n");
                        }
                    }
                    crate::log_error!("CSQTT_TEST_TUNCONF_HANDSHAKE_PARSED");
                }
                if let Some(sender) = &config_tx {
                    let _ = sender.try_send(value);
                }
                crate::log_error!("[ВОРКЕР #{}] Конфиг получен", config.id);"""
if session_patched.count(handshake_marker) != 1:
    raise SystemExit(f"Expected exactly one reconnect handshake config branch; found {session_patched.count(handshake_marker)}")
session_patched = session_patched.replace(handshake_marker, handshake_replacement, 1)
session_path.write_text(session_patched, encoding="utf-8")

# Instrument the disposable client so recovery assertions count every valid
# TUNCONF received, even when the assigned IP/DNS are unchanged and the normal
# UI/config event intentionally deduplicates identical config strings.
main_path = Path("client-source/rust-client/main.rs")
main_source = main_path.read_text(encoding="utf-8")
main_marker = """        while let Some(config) = config_rx.recv().await {
            if last_config.as_deref() == Some(config.as_str()) {"""
main_replacement = """        while let Some(config) = config_rx.recv().await {
            if config.starts_with("TUNCONF:") {
                crate::log_error!("CSQTT_TEST_TUNCONF_RECEIVED");
            }
            if last_config.as_deref() == Some(config.as_str()) {"""
if main_source.count(main_marker) != 1:
    raise SystemExit("Expected exactly one client config event loop marker; refusing test instrumentation")
main_patched = main_source.replace(main_marker, main_replacement, 1)

# Refactor only the disposable source clone so bootstrap parsing and the
# mode-combination gate can be tested without contacting VK or exposing tokens.
mode_gate_old = """    let js_hash_mode = arguments.vk_hash_mode == "auto_js";
    let js_auth_mode = arguments.vk_auth_mode == "auto_js";
    if js_auth_mode && !js_hash_mode {
        bail!("[КЛИЕНТ] Режим авторизации Auto JS требует режим хешей Auto JS");
    }
    if arguments.peer.is_empty() || (!js_hash_mode && arguments.vk.is_empty()) {
        bail!("[КЛИЕНТ] Нужны -peer и хеши VK");
    }
    if arguments.password.is_empty() {
        bail!("[КЛИЕНТ] Нужен -password: WRAP ключ выводится из пароля подключения");
    }
"""
mode_gate_new = """    validate_vk_mode_arguments(&arguments)?;
    let js_hash_mode = arguments.vk_hash_mode == "auto_js";
    let js_auth_mode = arguments.vk_auth_mode == "auto_js";
"""
if main_patched.count(mode_gate_old) != 1:
    raise SystemExit("Expected exactly one VK mode preflight gate; refusing test refactor")
main_patched = main_patched.replace(mode_gate_old, mode_gate_new, 1)

bootstrap_old = """async fn read_vk_js_bootstrap(token_argument: &str) -> Result<vk_js_calls::Bootstrap> {
    if !token_argument.trim().is_empty() {
        return Ok(vk_js_calls::Bootstrap {
            token: token_argument.trim().to_owned(),
        });
    }
    let mut line = String::new();
    tokio::time::timeout(
        Duration::from_secs(15),
        BufReader::new(tokio::io::stdin()).read_line(&mut line),
    )
    .await
    .context("тайм-аут передачи данных Auto JS")?
    .context("чтение данных Auto JS")?;
    let encoded = line
        .trim()
        .strip_prefix("VK_JS_BOOTSTRAP:")
        .context("неверный формат данных Auto JS")?;
    if encoded.len() > 32 * 1024 {
        bail!("слишком большие данные Auto JS");
    }
    let decoded = STANDARD
        .decode(encoded)
        .context("повреждены данные Auto JS")?;
    let bootstrap: vk_js_calls::Bootstrap =
        serde_json::from_slice(&decoded).context("некорректные данные Auto JS")?;
    Ok(bootstrap)
}
"""
bootstrap_new = """fn validate_vk_mode_arguments(arguments: &Arguments) -> Result<()> {
    let js_hash_mode = arguments.vk_hash_mode == "auto_js";
    let js_auth_mode = arguments.vk_auth_mode == "auto_js";
    if js_auth_mode && !js_hash_mode {
        bail!("[КЛИЕНТ] Режим авторизации Auto JS требует режим хешей Auto JS");
    }
    if arguments.peer.is_empty() || (!js_hash_mode && arguments.vk.is_empty()) {
        bail!("[КЛИЕНТ] Нужны -peer и хеши VK");
    }
    if arguments.password.is_empty() {
        bail!("[КЛИЕНТ] Нужен -password: WRAP ключ выводится из пароля подключения");
    }
    Ok(())
}

fn parse_vk_js_bootstrap_line(line: &str) -> Result<vk_js_calls::Bootstrap> {
    let encoded = line
        .trim()
        .strip_prefix("VK_JS_BOOTSTRAP:")
        .context("неверный формат данных Auto JS")?;
    if encoded.len() > 32 * 1024 {
        bail!("слишком большие данные Auto JS");
    }
    let decoded = STANDARD
        .decode(encoded)
        .context("повреждены данные Auto JS")?;
    let bootstrap: vk_js_calls::Bootstrap =
        serde_json::from_slice(&decoded).context("некорректные данные Auto JS")?;
    Ok(bootstrap)
}

async fn read_vk_js_bootstrap(token_argument: &str) -> Result<vk_js_calls::Bootstrap> {
    if !token_argument.trim().is_empty() {
        return Ok(vk_js_calls::Bootstrap {
            token: token_argument.trim().to_owned(),
        });
    }
    let mut line = String::new();
    tokio::time::timeout(
        Duration::from_secs(15),
        BufReader::new(tokio::io::stdin()).read_line(&mut line),
    )
    .await
    .context("тайм-аут передачи данных Auto JS")?
    .context("чтение данных Auto JS")?;
    parse_vk_js_bootstrap_line(&line)
}

#[cfg(test)]
mod csqtt_vk_mode_contract_tests {
    use super::*;

    fn args(vk_hash_mode: &str, vk_auth_mode: &str, vk: &str, password: &str) -> Arguments {
        Arguments::try_parse_from([
            "csqtt-client",
            "--peer", "127.0.0.1:46000",
            "--password", password,
            "--vk-hash-mode", vk_hash_mode,
            "--vk-auth-mode", vk_auth_mode,
            "--vk", vk,
        ]).unwrap()
    }

    #[test]
    fn manual_hash_with_vkcalls_auth_passes_preflight() {
        assert!(validate_vk_mode_arguments(&args("manual", "vkcalls", "fixture-hash", "fixture-password")).is_ok());
    }

    #[test]
    fn auto_js_hash_and_auth_modes_pass_preflight_without_manual_hash() {
        assert!(validate_vk_mode_arguments(&args("auto_js", "auto_js", "", "fixture-password")).is_ok());
    }

    #[test]
    fn auto_js_auth_cannot_be_combined_with_manual_hash_mode() {
        assert!(validate_vk_mode_arguments(&args("manual", "auto_js", "fixture-hash", "fixture-password")).is_err());
    }

    #[test]
    fn manual_mode_requires_hash_and_connection_password() {
        assert!(validate_vk_mode_arguments(&args("manual", "vkcalls", "", "fixture-password")).is_err());
        assert!(validate_vk_mode_arguments(&args("manual", "vkcalls", "fixture-hash", "")).is_err());
    }

    #[test]
    fn bootstrap_stdin_protocol_accepts_exact_prefix_and_json() {
        let payload = STANDARD.encode(br#"{"token":"fixture-token"}"#);
        let parsed = parse_vk_js_bootstrap_line(&format!("VK_JS_BOOTSTRAP:{payload}\n")).unwrap();
        assert_eq!(parsed.token, "fixture-token");
    }

    #[test]
    fn bootstrap_stdin_protocol_rejects_missing_prefix_invalid_base64_and_invalid_json() {
        assert!(parse_vk_js_bootstrap_line("eyJ0b2tlbiI6ImZpeHR1cmUifQ==").is_err());
        assert!(parse_vk_js_bootstrap_line("VK_JS_BOOTSTRAP:%%%").is_err());
        assert!(parse_vk_js_bootstrap_line(&format!("VK_JS_BOOTSTRAP:{}", STANDARD.encode(b"not-json"))).is_err());
    }

    #[test]
    fn bootstrap_stdin_protocol_rejects_oversized_payload() {
        assert!(parse_vk_js_bootstrap_line(&format!("VK_JS_BOOTSTRAP:{}",
            "A".repeat(32 * 1024 + 1))).is_err());
    }
}
"""
if main_patched.count(bootstrap_old) != 1:
    raise SystemExit("Expected exactly one VK JS bootstrap parser; refusing test refactor")
main_patched = main_patched.replace(bootstrap_old, bootstrap_new, 1)
main_path.write_text(main_patched, encoding="utf-8")
if watchdog_enabled:
    print("Applied disposable CI-only TURN credentials, opt-in receive watchdog, and pre-dedup TUNCONF parse instrumentation; secret values were not printed.")
else:
    print("Applied disposable CI-only TURN credentials and pre-dedup TUNCONF parse instrumentation; receive watchdog was not injected; secret values were not printed.")
