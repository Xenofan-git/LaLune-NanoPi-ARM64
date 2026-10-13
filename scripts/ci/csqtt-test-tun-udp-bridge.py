#!/usr/bin/env python3
"""Disposable CI TUN<->UDP bridge for the pinned CSQTT client process.

Creates one Linux TUN interface and forwards raw IPv4 packets to the real
client's local UDP dispatcher. Replies from that same client socket are written
back to TUN. This runs only inside the workflow's private network namespace.
"""
import fcntl
import os
import select
import socket
import struct
import sys
import time

TUNSETIFF = 0x400454CA
IFF_TUN = 0x0001
IFF_NO_PI = 0x1000
IFNAMSIZ = 16


def main() -> int:
    tun_name = os.environ.get("CSQTT_TEST_TUN_NAME", "csqtt-client0")
    listen_host = os.environ.get("CSQTT_TEST_CLIENT_LISTEN", "127.0.0.1")
    listen_port = int(os.environ.get("CSQTT_TEST_CLIENT_PORT", "9000"))
    tun_fd = os.open("/dev/net/tun", os.O_RDWR | os.O_CLOEXEC)
    request = struct.pack("16sH22x", tun_name.encode()[: IFNAMSIZ - 1], IFF_TUN | IFF_NO_PI)
    try:
        response = fcntl.ioctl(tun_fd, TUNSETIFF, request)
    except Exception:
        os.close(tun_fd)
        raise
    actual_name = response[:IFNAMSIZ].split(b"\0", 1)[0].decode()

    udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    udp.bind(("127.0.0.1", 0))
    udp.setblocking(False)
    os.set_blocking(tun_fd, False)
    peer = (listen_host, listen_port)
    print(f"CSQTT_TEST_TUN_BRIDGE_READY interface={actual_name} udp_local_port={udp.getsockname()[1]}", flush=True)

    try:
        while True:
            readable, _, _ = select.select([tun_fd, udp], [], [], 0.5)
            for source in readable:
                if source == tun_fd:
                    try:
                        packet = os.read(tun_fd, 65535)
                    except BlockingIOError:
                        continue
                    if packet:
                        udp.sendto(packet, peer)
                else:
                    try:
                        packet, sender = udp.recvfrom(65535)
                    except BlockingIOError:
                        continue
                    # The local dispatcher is the only intended sender in this
                    # private namespace; accept its reply packets only.
                    if sender[0] == listen_host and packet:
                        try:
                            os.write(tun_fd, packet)
                        except BlockingIOError:
                            time.sleep(0.001)
                            os.write(tun_fd, packet)
    except KeyboardInterrupt:
        return 0
    finally:
        udp.close()
        os.close(tun_fd)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"CSQTT_TEST_TUN_BRIDGE_ERROR {type(exc).__name__}: {exc}", file=sys.stderr, flush=True)
        raise
