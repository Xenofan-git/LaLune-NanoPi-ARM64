#!/usr/bin/env python3
"""Apply the negotiated WIRE-4 liveness patch to pinned CSQTT source checkouts.

The release workflow builds its production ARM64 client/server binaries from these
patched checkouts. The recovery E2E workflow applies the same patch plus separate
CI-only TURN/test instrumentation to disposable clones. No upstream repository is
modified. The authenticated PING/PONG exchange is gated by WIRE-4/TUNCONF capability.
"""
from pathlib import Path

def replace_once(path: str, old: str, new: str, label: str) -> None:
    p = Path(path)
    source = p.read_text(encoding="utf-8")
    count = source.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one match in {path}, found {count}")
    p.write_text(source.replace(old, new, 1), encoding="utf-8")

def replace_if_present(path: str, old: str, new: str, label: str) -> None:
    p = Path(path)
    source = p.read_text(encoding="utf-8")
    count = source.count(old)
    if count == 0:
        return
    if count != 1:
        raise SystemExit(f"{label}: expected at most one match in {path}, found {count}")
    p.write_text(source.replace(old, new, 1), encoding="utf-8")


# Negotiate a new revision only in the disposable clones. Preserve WIRE-3 server
# compatibility for old clients; only WIRE-4 clients get the liveness capability.
for path in ("client-source/shared/wire_protocol.rs", "server-source/shared/wire_protocol.rs"):
    replace_once(path, 'pub const WIRE_PROTOCOL_REVISION: &str = "CSQTT-WIRE-3";',
                 'pub const WIRE_PROTOCOL_REVISION: &str = "CSQTT-WIRE-4";',
                 "bump disposable protocol revision")

# Keep upstream unit fixtures aligned with the WIRE-4 revision under test.
# These are protocol expectation updates, not skipped or weakened tests.
replace_once("client-source/rust-client/protocol.rs",
             '"GETCONF:9000|device|password|7|salt|4||CSQTT-WIRE-3"',
             '"GETCONF:9000|device|password|7|salt|4||CSQTT-WIRE-4"',
             "update WIRE-4 request contract fixture")
replace_once("client-source/rust-client/protocol.rs",
             '"GETCONF:9000|device|password|7|salt|4|36|CSQTT-WIRE-3"',
             '"GETCONF:9000|device|password|7|salt|4|36|CSQTT-WIRE-4"',
             "update WIRE-4 optional capability fixture")
replace_once("client-source/rust-client/session.rs",
             'b"GETCONF:9000|device|password|7|generation-id|1|9|CSQTT-WIRE-3"',
             'b"GETCONF:9000|device|password|7|generation-id|1|9|CSQTT-WIRE-4"',
             "update WIRE-4 first registration fixture")

# The pinned upstream server repository also vendors a client crate used by
# the release protocol regression suite. Its fixtures share server-source/shared
# and must expect WIRE-4 after the negotiated revision is updated.
replace_once("server-source/rust-client/protocol.rs",
             '"GETCONF:9000|device|password|7|salt|4||CSQTT-WIRE-3"',
             '"GETCONF:9000|device|password|7|salt|4||CSQTT-WIRE-4"',
             "update vendored client WIRE-4 request fixture")
replace_once("server-source/rust-client/protocol.rs",
             '"GETCONF:9000|device|password|7|salt|4|36|CSQTT-WIRE-3"',
             '"GETCONF:9000|device|password|7|salt|4|36|CSQTT-WIRE-4"',
             "update vendored client WIRE-4 optional capability fixture")
replace_once("server-source/rust-client/session.rs",
             'b"GETCONF:9000|device|password|7|generation-id|1|9|CSQTT-WIRE-3"',
             'b"GETCONF:9000|device|password|7|generation-id|1|9|CSQTT-WIRE-4"',
             "update vendored client WIRE-4 registration fixture")


replace_once("server-source/rust-server/protocol.rs",
'''fn is_supported_wire_protocol(value: &str) -> bool {
    value == crate::wire_protocol::WIRE_PROTOCOL_REVISION
        || value == crate::wire_protocol::LEGACY_WIRE_PROTOCOL_REVISION
}

fn supports_data_frames(value: &str) -> bool {
    value == crate::wire_protocol::WIRE_PROTOCOL_REVISION
}''',
'''fn is_supported_wire_protocol(value: &str) -> bool {
    value == crate::wire_protocol::WIRE_PROTOCOL_REVISION
        || value == "CSQTT-WIRE-3"
        || value == crate::wire_protocol::LEGACY_WIRE_PROTOCOL_REVISION
}

fn supports_data_frames(value: &str) -> bool {
    value == crate::wire_protocol::WIRE_PROTOCOL_REVISION || value == "CSQTT-WIRE-3"
}''', "preserve WIRE-3 compatibility")

replace_once("server-source/rust-server/protocol.rs",
'''const SESSION_LEASE: &[u8] = b"\\xffCSQTT_LEASE";
pub const PANEL_RESTART_NOTICE''',
'''const SESSION_LEASE: &[u8] = b"\\xffCSQTT_LEASE";
const LIVENESS_PREFIX: &[u8] = b"\\xffCSQTT_LIVENESS_V1";
const LIVENESS_VERSION: u8 = 1;
const LIVENESS_PING: u8 = 1;
const LIVENESS_PONG: u8 = 2;
pub const PANEL_RESTART_NOTICE''', "server liveness constants")

replace_once("server-source/rust-server/protocol.rs",
'''fn is_dpi_control(plain: &[u8]) -> bool {
    plain.starts_with(b"GETCONF:")
        || plain.starts_with(b"TUNCONF:")
        || plain == PANEL_RESTART_NOTICE''',
'''fn is_dpi_control(plain: &[u8]) -> bool {
    plain.starts_with(b"GETCONF:")
        || plain.starts_with(b"TUNCONF:")
        || plain.starts_with(LIVENESS_PREFIX)
        || plain == PANEL_RESTART_NOTICE''', "exclude liveness from DPI sampling")

replace_once("server-source/rust-server/protocol.rs",
'''        || payload.starts_with(STREAM_ALIVE_PREFIX)
        || payload == b"READY"''',
'''        || payload.starts_with(STREAM_ALIVE_PREFIX)
        || payload.starts_with(LIVENESS_PREFIX)
        || payload == b"READY"''', "flush liveness responses promptly")

replace_once("server-source/rust-server/protocol.rs",
'''fn is_control_payload(payload: &[u8]) -> bool {
    payload.starts_with(b"GETCONF:")''',
'''fn liveness_pong(payload: &[u8]) -> Option<Vec<u8>> {
    const FRAME_LEN: usize = LIVENESS_PREFIX.len() + 26;
    if payload.len() != FRAME_LEN || !payload.starts_with(LIVENESS_PREFIX) {
        return None;
    }
    let offset = LIVENESS_PREFIX.len();
    if payload[offset] != LIVENESS_VERSION || payload[offset + 1] != LIVENESS_PING {
        return None;
    }
    if payload[offset + 2..offset + 10].iter().all(|byte| *byte == 0) {
        return None;
    }
    let mut pong = payload.to_vec();
    pong[offset + 1] = LIVENESS_PONG;
    Some(pong)
}

fn is_control_payload(payload: &[u8]) -> bool {
    payload.starts_with(b"GETCONF:")''', "server liveness frame validation")

replace_once("server-source/rust-server/protocol.rs",
'''    if payload.starts_with(b"GETCONF:") {
        let text = std::str::from_utf8(payload)?;''',
'''    if payload.starts_with(LIVENESS_PREFIX) {
        if let Some(pong) = liveness_pong(payload) {
            let offset = LIVENESS_PREFIX.len();
            let sequence = u64::from_be_bytes(pong[offset + 2..offset + 10].try_into()?);
            eprintln!("[LIVENESS_DIAG] SERVER_RX_PING session={} bytes={} valid=1 seq={}", session.id, payload.len(), sequence);
            writer.write(&pong).await?;
            eprintln!("[LIVENESS_DIAG] SERVER_TX_PONG session={} seq={}", session.id, sequence);
        } else {
            eprintln!("[LIVENESS_DIAG] SERVER_RX_PING session={} bytes={} valid=0", session.id, payload.len());
        }
        return Ok(());
    }
    if payload.starts_with(b"GETCONF:") {
        let text = std::str::from_utf8(payload)?;''', "server PING/PONG handler")

replace_once("server-source/rust-server/protocol.rs",
'''                        format!(
                            "TUNCONF:{}:{}:{}:{stream_revision}",
                            device.ip, dns, client_port
                        )''',
'''                        if protocol_revision == crate::wire_protocol::WIRE_PROTOCOL_REVISION {
                            format!(
                                "TUNCONF:{}:{}:{}:{stream_revision}:liveness-v1",
                                device.ip, dns, client_port
                            )
                        } else {
                            format!(
                                "TUNCONF:{}:{}:{}:{stream_revision}",
                                device.ip, dns, client_port
                            )
                        }''', "server confirms negotiated liveness")

# The LaLune adaptation injects a server/client round-trip test before this
# patch runs. Keep that test aligned with the negotiated WIRE-4 request and
# the WIRE-4 TUNCONF capability marker; otherwise the release server test
# fails against its own intentionally upgraded protocol fixture.
replace_if_present("server-source/rust-server/protocol.rs",
             '"GETCONF:9000|wire-device|wire-password|7|ci-salt|1|1|CSQTT-WIRE-3"',
             '"GETCONF:9000|wire-device|wire-password|7|ci-salt|1|1|CSQTT-WIRE-4"',
             "update injected server WIRE-4 request fixture")
replace_if_present("server-source/rust-server/protocol.rs",
             'b"TUNCONF:10.67.68.42:1.1.1.1,8.8.8.8:0:stream-v2"',
             'b"TUNCONF:10.67.68.42:1.1.1.1,8.8.8.8:0:stream-v2:liveness-v1"',
             "update injected WIRE-4 TUNCONF fixture")
replace_if_present("server-source/rust-server/protocol.rs",
             '["10.67.68.42", "1.1.1.1,8.8.8.8", "0", "stream-v2"]',
             '["10.67.68.42", "1.1.1.1,8.8.8.8", "0", "stream-v2", "liveness-v1"]',
             "update injected WIRE-4 TUNCONF parser assertion")

# Client-side codec and runtime. PINGs use the existing authenticated packet envelope.
replace_once("client-source/rust-client/session.rs",
'''const CONFIG_RESPONSE_TIMEOUT_MS: [u64; 3] = [750, 1_500, 3_000];''',
'''const CONFIG_RESPONSE_TIMEOUT_MS: [u64; 3] = [750, 1_500, 3_000];
const LIVENESS_PREFIX: &[u8] = b"\\xffCSQTT_LIVENESS_V1";
const LIVENESS_VERSION: u8 = 1;
const LIVENESS_PING: u8 = 1;
const LIVENESS_PONG: u8 = 2;
const LIVENESS_INTERVAL: Duration = Duration::from_secs(5);
const LIVENESS_TIMEOUT: Duration = Duration::from_secs(15);

fn liveness_frame(kind: u8, sequence: u64, nonce: &[u8; 16]) -> Vec<u8> {
    let mut frame = Vec::with_capacity(LIVENESS_PREFIX.len() + 26);
    frame.extend_from_slice(LIVENESS_PREFIX);
    frame.push(LIVENESS_VERSION);
    frame.push(kind);
    frame.extend_from_slice(&sequence.to_be_bytes());
    frame.extend_from_slice(nonce);
    frame
}

fn parse_liveness_pong(frame: &[u8]) -> Option<(u64, [u8; 16])> {
    if frame.len() != LIVENESS_PREFIX.len() + 26 || !frame.starts_with(LIVENESS_PREFIX) {
        return None;
    }
    let offset = LIVENESS_PREFIX.len();
    if frame[offset] != LIVENESS_VERSION || frame[offset + 1] != LIVENESS_PONG {
        return None;
    }
    let sequence = u64::from_be_bytes(frame[offset + 2..offset + 10].try_into().ok()?);
    if sequence == 0 {
        return None;
    }
    let nonce = frame[offset + 10..offset + 26].try_into().ok()?;
    Some((sequence, nonce))
}''', "client liveness codec")

replace_once("client-source/rust-client/session.rs",
'''struct ReaderRuntime {
    dispatcher: Arc<Dispatcher>,
    events: Events,
    repair: Arc<RepairState>,
    shutdown: Arc<ShutdownCoordinator>,
    config_tx: mpsc::Sender<String>,
}''',
'''struct ReaderRuntime {
    dispatcher: Arc<Dispatcher>,
    events: Events,
    repair: Arc<RepairState>,
    shutdown: Arc<ShutdownCoordinator>,
    config_tx: mpsc::Sender<String>,
    writer: mpsc::Sender<WriterCommand>,
    liveness_enabled: bool,
    stream_id: usize,
}''', "reader runtime liveness fields")

replace_once("client-source/rust-client/session.rs",
'''    let config_delivered = match request_configuration(
        &mut writer_transport,
        &mut reader_transport,
        &config,
        &runtime.events,
        config_tx,
    )
    .await
    {
        Ok(delivered) => {
            let delivered = config.get_config && delivered;''',
'''    let (config_delivered, liveness_enabled) = match request_configuration(
        &mut writer_transport,
        &mut reader_transport,
        &config,
        &runtime.events,
        config_tx,
    )
    .await
    {
        Ok((delivered, liveness)) => {
            let delivered = config.get_config && delivered;''', "carry negotiated liveness out of handshake")

replace_once("client-source/rust-client/session.rs",
'''            if let Some(state) = &runtime.config_delivery {
                state.complete(delivered);
            }
            delivered
        }
        Err(error) => {''',
'''            if let Some(state) = &runtime.config_delivery {
                state.complete(delivered);
            }
            (delivered, liveness)
        }
        Err(error) => {''', "return handshake capability")

replace_once("client-source/rust-client/session.rs",
'''        ReaderRuntime {
            dispatcher: runtime.dispatcher.clone(),
            events: runtime.events.clone(),
            repair: config.repair.clone(),
            shutdown: runtime.shutdown.clone(),
            config_tx: runtime.config_tx.clone(),
        },''',
'''        ReaderRuntime {
            dispatcher: runtime.dispatcher.clone(),
            events: runtime.events.clone(),
            repair: config.repair.clone(),
            shutdown: runtime.shutdown.clone(),
            config_tx: runtime.config_tx.clone(),
            writer: writer_command_tx.clone(),
            liveness_enabled,
            stream_id: config.id,
        },''', "wire reader liveness state")

replace_once("client-source/rust-client/session.rs",
'''    config_tx: Option<mpsc::Sender<String>>,
) -> Result<bool> {
    let request = build_registration_payload(config);''',
'''    config_tx: Option<mpsc::Sender<String>>,
) -> Result<(bool, bool)> {
    let request = build_registration_payload(config);''', "handshake return type")

replace_once("client-source/rust-client/session.rs",
'''            ConfigResponse::NoConfig => return Ok(false),''',
'''            ConfigResponse::NoConfig => return Ok((false, false)),''', "no-config handshake result")

replace_once("client-source/rust-client/session.rs",
'''                if value.ends_with(":stream-v1") || value.ends_with(":stream-v2") {
                    config.server_stream_repair.store(true, Ordering::Release);
                }''',
'''                if value.contains(":stream-v1") || value.contains(":stream-v2") {
                    config.server_stream_repair.store(true, Ordering::Release);
                }
                let liveness_enabled = value.ends_with(":liveness-v1");''', "detect exact liveness confirmation")

replace_once("client-source/rust-client/session.rs",
'''                return Ok(true);
            }
        }
    }
    let message = "FATAL_HANDSHAKE: сервер не подтвердил конфигурацию";''',
'''                return Ok((true, liveness_enabled));
            }
        }
    }
    let message = "FATAL_HANDSHAKE: сервер не подтвердил конфигурацию";''', "return negotiated capability")

replace_once("client-source/rust-client/session.rs",
'''    let ReaderRuntime {
        dispatcher,
        events,
        repair,
        shutdown,
        config_tx,
    } = runtime;
    loop {
        let packet = tokio::select! {
            biased;
            _ = cancel.cancelled() => return Ok(()),
            result = transport.recv() => result?,
        };''',
'''    let ReaderRuntime {
        dispatcher,
        events,
        repair,
        shutdown,
        config_tx,
        writer,
        liveness_enabled,
        stream_id,
    } = runtime;
    let mut liveness_tick = tokio::time::interval(LIVENESS_INTERVAL);
    liveness_tick.tick().await;
    let mut pending_probe: Option<(u64, [u8; 16], tokio::time::Instant)> = None;
    let mut next_sequence = 1u64;
    loop {
        let packet = tokio::select! {
            biased;
            _ = cancel.cancelled() => return Ok(()),
            _ = liveness_tick.tick(), if liveness_enabled => {
                if let Some((_, _, sent_at)) = pending_probe {
                    if sent_at.elapsed() >= LIVENESS_TIMEOUT {
                        bail!("CSQTT negotiated liveness PONG timeout");
                    }
                } else {
                    let sequence = next_sequence;
                    next_sequence = next_sequence.checked_add(1)
                        .ok_or_else(|| anyhow::anyhow!("CSQTT liveness sequence exhausted"))?;
                    let nonce = rand::random::<[u8; 16]>();
                    let frame = liveness_frame(LIVENESS_PING, sequence, &nonce);
                    eprintln!("[LIVENESS_DIAG] CLIENT_TX_PING stream={} seq={} bytes={}", stream_id, sequence, frame.len());
                    send_writer_bytes(&writer, &frame).await.context("send CSQTT liveness PING")?;
                    pending_probe = Some((sequence, nonce, tokio::time::Instant::now()));
                }
                continue;
            }
            result = transport.recv() => result?,
        };
        if liveness_enabled && packet.as_slice().starts_with(LIVENESS_PREFIX) {
            let parsed = parse_liveness_pong(packet.as_slice());
            eprintln!("[LIVENESS_DIAG] CLIENT_RX_FRAME stream={} bytes={} parsed={}", stream_id, packet.len(), u8::from(parsed.is_some()));
            if let (Some((expected_sequence, expected_nonce, _)), Some((sequence, nonce))) =
                (pending_probe, parsed)
            {
                if sequence == expected_sequence && nonce == expected_nonce {
                    eprintln!("[LIVENESS_DIAG] CLIENT_RX_PONG stream={} seq={}", stream_id, sequence);
                    pending_probe = None;
                } else {
                    eprintln!("[LIVENESS_DIAG] CLIENT_RX_PONG_MISMATCH stream={} expected_seq={} received_seq={} nonce_match={}", stream_id, expected_sequence, sequence, u8::from(expected_nonce == nonce));
                }
            }
            continue;
        }''', "reader handles negotiated PING/PONG and bounded failure")

replace_once("client-source/rust-client/protocol.rs",
'''        STREAM_REPAIR_PREFIX,
        STREAM_ALIVE_PREFIX,
    ]''',
'''        STREAM_REPAIR_PREFIX,
        STREAM_ALIVE_PREFIX,
        b"\\xffCSQTT_LIVENESS_V1",
    ]''', "classify liveness as control")

# Diagnostics are emitted only by the CI recovery binary and disposable server.
print("PASS: installed per-stream WIRE-4 PING/PONG diagnostics in CI-only source clones.")
