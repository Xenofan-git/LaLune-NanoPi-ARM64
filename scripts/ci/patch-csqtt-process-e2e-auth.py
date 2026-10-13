#!/usr/bin/env python3
"""Patch the pinned CSQTT client checkout for isolated process-level E2E only.

The patch is applied to a disposable CI clone, never to upstream or production.
Without all three explicit CSQTT_TEST_TURN_* variables the stock VK auth path
is unchanged. Credential values are never logged.
"""
from pathlib import Path

# Patch the disposable client with a bounded receive-silence watchdog. A TURN
# allocation can survive a CSQTT server restart, leaving the reader blocked.
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
session_patched = session_source.replace(recv_marker, recv_replacement, 1)

# Instrument both client-side protocol parse paths, before optional config
# delivery/deduplication, so the test can distinguish server send from client
# actually parsing the response.
handshake_marker = """            ConfigResponse::Config(value) => {
                if value.ends_with(":stream-v1")"""
handshake_replacement = """            ConfigResponse::Config(value) => {
                if let Ok(path) = std::env::var("CSQTT_TEST_TUNCONF_COUNTER_FILE") {
                    if let Ok(mut file) = std::fs::OpenOptions::new().create(true).append(true).open(path) {
                        let _ = std::io::Write::write_all(&mut file, b"TUNCONF\\n");
                    }
                }
                crate::log_error!("CSQTT_TEST_TUNCONF_PARSED");
                if value.ends_with(":stream-v1")"""
if session_patched.count(handshake_marker) != 1:
    raise SystemExit("Expected exactly one client handshake TUNCONF parse branch; refusing instrumentation")
session_patched = session_patched.replace(handshake_marker, handshake_replacement, 1)
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
main_path.write_text(main_source.replace(main_marker, main_replacement, 1), encoding="utf-8")
print("Applied disposable CI-only TURN credentials, receive watchdog, and pre-dedup TUNCONF parse instrumentation; secret values were not printed.")
