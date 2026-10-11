#!/usr/bin/env python3
"""Patch pinned upstream CSQTT v2.1.9 source for an isolated LaLune dataplane."""
from pathlib import Path

root = Path("server-source/rust-server")
paths = {
    "net": root / "net_setup.rs",
    "tun": root / "tun_device.rs",
    "proxy": root / "proxy_route.rs",
    "model": root / "model.rs",
    "protocol": root / "protocol.rs",
}
sources = {key: path.read_text() for key, path in paths.items()}
replacements = [
    ("net", 'pub const TUN_IFACE: &str = "csqtt1";', 'pub const TUN_IFACE: &str = "csqtt-lalune0";', "net_setup TUN interface", 1),
    ("net", 'pub const TUN_ADDR: &str = "10.66.67.1";', 'pub const TUN_ADDR: &str = "10.67.68.1";', "net_setup TUN address", 1),
    ("tun", 'pub const TUN_IFACE: &str = "csqtt1";', 'pub const TUN_IFACE: &str = "csqtt-lalune0";', "tun_device TUN interface", 1),
    ("tun", 'pub const TUN_SUBNET: &str = "10.66.67.0/24";', 'pub const TUN_SUBNET: &str = "10.67.68.0/24";', "TUN subnet", 1),
    ("tun", 'const SUBNET_PREFIX: [u8; 3] = [10, 66, 67];', 'const SUBNET_PREFIX: [u8; 3] = [10, 67, 68];', "route prefix", 1),
    ("tun", '[10, 66, 67, last]', '[10, 67, 68, last]', "subnet helper", 1),
    # Upstream uses this foreign-subnet test address twice; both occurrences must move
    # together so runtime logic and its unit test agree with the new LaLune subnet.
    ("tun", '[10, 66, 68, 2]', '[10, 67, 69, 2]', "foreign subnet reference", 2),
    # Protocol fixtures embed the allocated client subnet in expected payloads.
    ("protocol", "10.66.67", "10.67.68", "protocol client subnet", 2),
    # The hot tunnel-configuration test formats this address from octets, so
    # rewriting dotted-decimal fixtures alone leaves the runtime test on the old subnet.
    ("protocol", "[10, 66, 67, 42]", "[10, 67, 68, 42]", "hot tunnel configuration numeric subnet fixture", 1),
]
for key, old, new, label, expected_count in replacements:
    count = sources[key].count(old)
    if count != expected_count:
        raise SystemExit(f"{label}: expected {expected_count} source occurrence(s), found {count}")
    sources[key] = sources[key].replace(old, new)

# Bind the pinned client parser into the server's test module. This is test-only:
# it lets a real server-produced encrypted response pass through the exact client parser
# without introducing a second implementation or shipping client code in the server.
client_protocol_test_module = '''
mod client_protocol {
    include!("../rust-client/protocol.rs");
}
'''
import re

# Match the Rust test module structurally: whitespace between cfg(test) and
# mod tests may differ across upstream formatting revisions.
marker_pattern = re.compile(r'(?m)^#\[cfg\(test\)\]\s*^mod tests \{')
match = marker_pattern.search(sources["protocol"])
if not match or marker_pattern.search(sources["protocol"], match.end()):
    raise SystemExit("protocol.rs: expected one test module for real client parser binding")
marker = match.group(0)
insertion = "\n    " + client_protocol_test_module.strip().replace("\n", "\n    ")
sources["protocol"] = sources["protocol"][:match.end()] + insertion + sources["protocol"][match.end():]

dataplane_test = '''
    struct CaptureSink {
        udp: Vec<Vec<u8>>,
        tun: Vec<Vec<u8>>,
    }

    impl CaptureSink {
        fn new() -> Self {
            Self { udp: Vec::new(), tun: Vec::new() }
        }
    }

    impl PacketOutput for CaptureSink {
        fn has_udp_tx_slot(&self) -> bool { true }

        fn send_udp_with_duplicate_priority<F>(
            &mut self,
            _peer: SocketAddr,
            _source_ip: Option<IpAddr>,
            _duplicate: bool,
            _class: crate::striped_scheduler::PacketClass,
            build: F,
        ) -> bool
        where
            F: FnOnce(&mut PacketBuf) -> bool,
        {
            let pool = crate::packet::PacketPool::new(1);
            let Some(mut packet) = pool.try_acquire() else { return false; };
            if !build(&mut packet) { return false; }
            self.udp.push(packet.as_slice().to_vec());
            true
        }

        fn request_udp_flush(&mut self) {}

        fn write_tun_priority(
            &mut self,
            payload: &[u8],
            _class: crate::striped_scheduler::PacketClass,
        ) -> bool {
            self.tun.push(payload.to_vec());
            true
        }
    }

    fn ipv4_packet(src: [u8; 4], dst: [u8; 4], marker: u8) -> Vec<u8> {
        let mut packet = vec![0u8; 28];
        packet[0] = 0x45;
        let packet_len = packet.len() as u16;
        packet[2..4].copy_from_slice(&packet_len.to_be_bytes());
        packet[8] = 64;
        packet[9] = 17;
        packet[12..16].copy_from_slice(&src);
        packet[16..20].copy_from_slice(&dst);
        packet[20..28].copy_from_slice(&[marker, 1, 2, 3, 4, 5, 6, 7]);
        packet
    }

    #[test]
    fn encrypted_ipv4_packets_cross_server_tun_in_both_directions() {
        let (mut engine, _events, _worker_output) =
            fixture_engine_with_worker("wire-password", 0, 1);
        let peer = SocketAddr::from(([198, 51, 100, 20], 46000));
        engine.handle_unknown_legacy(peer, None, &fixture_wire());
        assert_eq!(engine.sessions.len(), 1);
        let session_id = engine.sessions.iter().next().unwrap().id;
        assert!(engine.activate_tunnel(session_id, [10, 67, 68, 42], 77, 1, 1));

        // Client -> server: the authenticated encrypted UDP payload must emerge
        // from the server's TUN sink as the identical IPv4 packet.
        let client_packet = ipv4_packet([10, 67, 68, 42], [192, 0, 2, 10], 0xa1);
        let mut client_wire = {
            let slot = engine.by_id.get(&session_id).copied().unwrap();
            let session = engine.sessions.get_mut(slot).unwrap();
            let pool = crate::packet::PacketPool::new(1);
            let mut output = pool.try_acquire().unwrap();
            let mut rng = StdRng::seed_from_u64(0x434c_4945_4e54);
            wrap_legacy_into(session, &client_packet, &mut rng, &mut output, Instant::now(), false).unwrap();
            output.as_slice().to_vec()
        };
        let mut sink = CaptureSink::new();
        engine.on_udp(peer, None, &mut client_wire, &mut sink);
        assert_eq!(sink.tun, vec![client_packet], "client IPv4 packet must be delivered to server TUN");

        // Server -> client: a packet addressed to the active tunnel IP must be
        // routed, encrypted with the established session, and recover unchanged.
        let server_packet = ipv4_packet([192, 0, 2, 10], [10, 67, 68, 42], 0xb2);
        let mut server_input = server_packet.clone();
        engine.on_tun(&mut server_input, &mut sink);
        engine.on_tun_batch_end(&mut sink);
        assert_eq!(sink.udp.len(), 1, "server TUN packet must produce an encrypted UDP datagram");
        let mut server_wire = sink.udp.pop().unwrap();
        let decoded = {
            let slot = engine.by_id.get(&session_id).copied().unwrap();
            let session = engine.sessions.get(slot).unwrap();
            unwrap_legacy_in_place(&session.aes, &session.hmac, &session.chacha, &mut server_wire, Some(session.is_srtp), false)
                .expect("server-to-client datagram must authenticate and decrypt")
        };
        let plain = decoded.range.get(&server_wire);
        assert_eq!(flow_frame::payload(plain), server_packet.as_slice(), "client must recover identical IPv4 packet");
    }
'''

roundtrip_test = '''
    #[test]
    fn server_encrypted_tunconf_roundtrips_through_real_client_parser() {
        let (mut engine, _events) = fixture_engine("wire-password");
        engine.handle_unknown_legacy(
            SocketAddr::from(([198, 51, 100, 20], 46000)),
            None,
            &fixture_wire(),
        );
        assert_eq!(engine.sessions.len(), 1);

        let session = engine.sessions.iter_mut().next().unwrap().1;
        let expected = b"TUNCONF:10.67.68.42:1.1.1.1,8.8.8.8:0:stream-v2";
        let pool = crate::packet::PacketPool::new(1);
        let mut packet = pool.try_acquire().expect("packet buffer");
        let mut rng = StdRng::seed_from_u64(0x4353_5154_545f_4349);
        wrap_legacy_into(session, expected, &mut rng, &mut packet, Instant::now(), false)
            .expect("server must encrypt TUNCONF using the established session keys");

        let mut wire = packet.as_slice().to_vec();
        let decoded = unwrap_legacy_in_place(
            &session.aes,
            &session.hmac,
            &session.chacha,
            &mut wire,
            None,
            false,
        )
        .expect("session-authenticated TUNCONF must decrypt");
        let plaintext = decoded.range.get(&wire);
        assert_eq!(plaintext, expected);
        assert_eq!(
            client_protocol::parse_config_response(plaintext).unwrap(),
            client_protocol::ConfigResponse::Config(
                "TUNCONF:10.67.68.42:1.1.1.1,8.8.8.8:0:stream-v2".to_owned()
            )
        );
    }
'''
test_anchor = '''
    #[test]
    fn client_getconf_fixture_authenticates_with_matching_password_only() {'''
if sources["protocol"].count(test_anchor) != 1:
    raise SystemExit("protocol.rs: expected unique GETCONF authentication test anchor")
sources["protocol"] = sources["protocol"].replace(test_anchor, dataplane_test + roundtrip_test + test_anchor, 1)

# Device address allocation and legacy-import fixtures also embed the upstream subnet.
# Move every occurrence in model.rs so newly allocated client IPs use the LaLune subnet.
model_count = sources["model"].count("10.66.67")
if model_count < 1:
    raise SystemExit("model.rs: expected legacy client subnet references to rename")
sources["model"] = sources["model"].replace("10.66.67", "10.67.68")

# The proxy-route module also writes rp_filter against the TUN name and
# mutates policy routing / iptables. Give every policy table, mark, and rule
# comment its own namespace; otherwise its startup/cleanup can delete another
# CSQTT instance's rules or flush a shared routing table.
proxy_count = sources["proxy"].count("csqtt1")
if proxy_count < 1:
    raise SystemExit("proxy_route.rs: expected legacy TUN references to rename")
sources["proxy"] = sources["proxy"].replace("csqtt1", "csqtt-lalune0")

proxy_policy_replacements = [
    ('const LEGACY_POLICY_TABLE: &str = "1066";', 'const LEGACY_POLICY_TABLE: &str = "47066";', "legacy policy table"),
    ('const LEGACY_POLICY_PRIORITY: &str = "1066";', 'const LEGACY_POLICY_PRIORITY: &str = "47066";', "legacy policy priority"),
    ('const NAT_COMMENT: &str = "CSQTT_LOCAL_SOCKS";', 'const NAT_COMMENT: &str = "CSQTT_LALUNE_LOCAL_SOCKS";', "local SOCKS NAT marker"),
    ('const MARK_COMMENT: &str = "CSQTT_LOCAL_SOCKS_MARK";', 'const MARK_COMMENT: &str = "CSQTT_LALUNE_LOCAL_SOCKS_MARK";', "local SOCKS mark marker"),
    ('const POLICY_MARK: &str = "0x422";', 'const POLICY_MARK: &str = "0x6742";', "local SOCKS policy mark"),
    ('const LEGACY_NAT_COMMENT: &str = "CSQTT_SOCKS";', 'const LEGACY_NAT_COMMENT: &str = "CSQTT_LALUNE_SOCKS";', "legacy NAT marker"),
    ('const LEGACY_QUIC_COMMENT: &str = "CSQTT_CASCADE_NO_QUIC";', 'const LEGACY_QUIC_COMMENT: &str = "CSQTT_LALUNE_CASCADE_NO_QUIC";', "legacy QUIC marker"),
    ('const TPROXY_TABLE: &str = "30001";', 'const TPROXY_TABLE: &str = "47001";', "TPROXY table"),
    ('const TPROXY_PRIORITY: &str = "30001";', 'const TPROXY_PRIORITY: &str = "47001";', "TPROXY priority"),
    ('const TPROXY_RULE_MARK: &str = "0x7531/0x7531";', 'const TPROXY_RULE_MARK: &str = "0x6741/0x6741";', "TPROXY mark"),
]
for old, new, label in proxy_policy_replacements:
    count = sources["proxy"].count(old)
    if count != 1:
        raise SystemExit(f"proxy_route.rs {label}: expected one declaration, found {count}")
    sources["proxy"] = sources["proxy"].replace(old, new, 1)

# Update exact numeric fixtures too, so tests exercise the namespaced values.
for old, new in [
    ('"1066"', '"47066"'),
    ('"30001"', '"47001"'),
    ('"0x422"', '"0x6742"'),
    ('"0x7531/0x7531"', '"0x6741/0x6741"'),
]:
    sources["proxy"] = sources["proxy"].replace(old, new)

# Runtime cleanup parses textual `ip rule show` output. These strings are
# executable cleanup logic, not just test fixtures, so namespace them explicitly.
for old, new, label in [
    ('starts_with("30001:")', 'starts_with("47001:")', "TPROXY priority cleanup matcher"),
    ('contains("fwmark 0x7531")', 'contains("fwmark 0x6741")', "TPROXY mark cleanup matcher"),
    ('contains("lookup 30001")', 'contains("lookup 47001")', "TPROXY table cleanup matcher"),
    ('starts_with("1066:")', 'starts_with("47066:")', "legacy priority cleanup matcher"),
    ('contains("lookup 1066")', 'contains("lookup 47066")', "legacy table cleanup matcher"),
    ('contains("fwmark 0x422")', 'contains("fwmark 0x6742")', "legacy mark cleanup matcher"),
]:
    count = sources["proxy"].count(old)
    if count != 1:
        raise SystemExit(f"proxy_route.rs {label}: expected one matcher, found {count}")
    sources["proxy"] = sources["proxy"].replace(old, new, 1)

# Flushing the kernel route cache is host-global and can disturb unrelated
# routing domains. LaLune must mutate only its explicitly numbered policy tables.
global_route_cache_flush = 'command_output("ip", &["route", "flush", "cache"])'
global_route_cache_flush_count = sources["proxy"].count(global_route_cache_flush)
if global_route_cache_flush_count != 2:
    raise SystemExit(
        "proxy_route.rs: expected exactly two global route-cache flushes to remove, "
        f"found {global_route_cache_flush_count}"
    )
sources["proxy"] = sources["proxy"].replace(
    '    let _ = command_output("ip", &["route", "flush", "cache"]).await;\n', ""
)
if global_route_cache_flush in sources["proxy"]:
    raise SystemExit("global route-cache flush remains in proxy_route.rs")

# Rule cleanup is marker-based, so the TPROXY comment must be unique as well.
sources["proxy"] = sources["proxy"].replace("CSQTT_TPROXY", "CSQTT_LALUNE_TPROXY")

for key, path in paths.items():
    path.write_text(sources[key])

for path in root.glob("*.rs"):
    text = path.read_text()
    if "csqtt1" in text or "10.66.67" in text:
        raise SystemExit(f"unpatched shared interface/subnet reference remains in {path}")
if 'pub const TUN_IFACE: &str = "csqtt-lalune0";' not in sources["net"]:
    raise SystemExit("dedicated interface missing from net_setup.rs")
if 'pub const TUN_IFACE: &str = "csqtt-lalune0";' not in sources["tun"]:
    raise SystemExit("dedicated interface missing from tun_device.rs")
if 'pub const TUN_SUBNET: &str = "10.67.68.0/24";' not in sources["tun"]:
    raise SystemExit("dedicated subnet missing")
if '[10, 67, 69, 2]' not in sources["tun"]:
    raise SystemExit("foreign subnet test reference missing after patch")
for marker in [
    'const LEGACY_POLICY_TABLE: &str = "47066";',
    'const TPROXY_TABLE: &str = "47001";',
    'const TPROXY_RULE_MARK: &str = "0x6741/0x6741";',
    'const NAT_COMMENT: &str = "CSQTT_LALUNE_LOCAL_SOCKS";',
    'CSQTT_LALUNE_TPROXY',
]:
    if marker not in sources["proxy"]:
        raise SystemExit(f"dedicated proxy routing namespace missing: {marker}")
for forbidden in ['"1066"', '"30001"', '"0x422"', '"0x7531/0x7531"', 'starts_with("30001:")', 'fwmark 0x7531', 'lookup 30001', 'starts_with("1066:")', 'lookup 1066', 'fwmark 0x422', 'CSQTT_TPROXY', 'CSQTT_LOCAL_SOCKS', 'CSQTT_SOCKS', 'route flush cache']:
    if forbidden in sources["proxy"]:
        raise SystemExit(f"shared proxy-routing operation/marker remains: {forbidden}")
print("Patched CSQTT v2.1.9: TUN=csqtt-lalune0, subnet=10.67.68.0/24, isolated policy tables; no global route-cache flush")
