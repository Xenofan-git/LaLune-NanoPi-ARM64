#!/usr/bin/env python3
"""Executable design tests for the proposed negotiated CSQTT liveness control.

This is deliberately a protocol-model test, not a live CSQTT wire test. The
client/server integration gate remains closed until the same frames are sent
through the pinned Rust client/server packet paths in the disposable E2E.
"""
from dataclasses import dataclass
import secrets
import struct
import unittest

MAGIC = b"\xffCSQTT_LIVENESS_V1"
PING = 1
PONG = 2
CAPABILITY = 1
HEADER = len(MAGIC) + 1 + 1 + 8 + 16
MAX_FRAME = HEADER


def encode(kind: int, sequence: int, nonce: bytes) -> bytes:
    if kind not in (PING, PONG):
        raise ValueError("unknown control type")
    if not 0 < sequence < (1 << 64):
        raise ValueError("sequence must be non-zero u64")
    if len(nonce) != 16:
        raise ValueError("nonce must be exactly 16 bytes")
    return MAGIC + bytes((CAPABILITY, kind)) + struct.pack(">Q", sequence) + nonce


def decode(frame: bytes):
    if len(frame) != MAX_FRAME or not frame.startswith(MAGIC):
        return None
    pos = len(MAGIC)
    version, kind = frame[pos], frame[pos + 1]
    if version != CAPABILITY or kind not in (PING, PONG):
        return None
    sequence = struct.unpack(">Q", frame[pos + 2:pos + 10])[0]
    nonce = frame[pos + 10:pos + 26]
    if sequence == 0:
        return None
    return kind, sequence, nonce


@dataclass
class ProbeState:
    next_sequence: int = 1
    pending: tuple | None = None
    missed: int = 0
    max_missed: int = 3

    def challenge(self):
        if self.pending is not None:
            self.missed += 1
            if self.missed >= self.max_missed:
                return "failed"
            return "pending"
        nonce = secrets.token_bytes(16)
        seq = self.next_sequence
        self.next_sequence += 1
        self.pending = (seq, nonce)
        return encode(PING, seq, nonce)

    def accept_pong(self, frame: bytes) -> bool:
        parsed = decode(frame)
        if parsed is None or parsed[0] != PONG or self.pending is None:
            return False
        _, seq, nonce = parsed
        if (seq, nonce) != self.pending:
            return False
        self.pending = None
        self.missed = 0
        return True


class LivenessProtocolModelTests(unittest.TestCase):
    def test_ping_pong_round_trip_echo(self):
        client = ProbeState()
        ping = client.challenge()
        kind, seq, nonce = decode(ping)
        self.assertEqual(kind, PING)
        self.assertTrue(client.accept_pong(encode(PONG, seq, nonce)))

    def test_idle_probe_is_independent_of_payload_activity(self):
        client = ProbeState()
        first = client.challenge()
        self.assertIsInstance(first, bytes)
        self.assertEqual(client.challenge(), "pending")
        self.assertTrue(client.accept_pong(encode(PONG, *decode(first)[1:])))
        self.assertIsInstance(client.challenge(), bytes)

    def test_unsolicited_stale_duplicate_and_wrong_nonce_are_rejected(self):
        client = ProbeState()
        self.assertFalse(client.accept_pong(encode(PONG, 1, b"x" * 16)))
        ping = client.challenge()
        _, seq, nonce = decode(ping)
        self.assertFalse(client.accept_pong(encode(PONG, seq, b"y" * 16)))
        self.assertTrue(client.accept_pong(encode(PONG, seq, nonce)))
        self.assertFalse(client.accept_pong(encode(PONG, seq, nonce)))

    def test_malformed_or_unknown_frames_are_rejected(self):
        ping = encode(PING, 1, b"n" * 16)
        self.assertIsNone(decode(ping[:-1]))
        self.assertIsNone(decode(ping + b"extra"))
        self.assertIsNone(decode(MAGIC + bytes((99, PING)) + ping[len(MAGIC)+2:]))
        self.assertIsNone(decode(encode(PING, 1, b"n" * 16)[:len(MAGIC)] + b"\x01\x01" + b"\x00"*24))

    def test_loss_requires_bounded_consecutive_failures(self):
        client = ProbeState(max_missed=3)
        self.assertIsInstance(client.challenge(), bytes)
        self.assertEqual(client.challenge(), "pending")
        self.assertEqual(client.challenge(), "pending")
        self.assertEqual(client.challenge(), "failed")

    def test_valid_pong_resets_missed_count(self):
        client = ProbeState(max_missed=3)
        ping = client.challenge()
        _, seq, nonce = decode(ping)
        self.assertTrue(client.accept_pong(encode(PONG, seq, nonce)))
        self.assertEqual(client.missed, 0)
        self.assertIsInstance(client.challenge(), bytes)


if __name__ == "__main__":
    unittest.main(verbosity=2)
