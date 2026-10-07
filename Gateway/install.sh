#!/bin/sh
set -eu
install -d -m 0755 /usr/local/bin /etc/lalune /var/lib/lalune
install -m 0755 lalune-gateway /usr/local/bin/lalune-gateway
install -m 0644 lalune-gateway.service /etc/systemd/system/lalune-gateway.service
if [ ! -s /etc/lalune/wg-private.key ]; then umask 077; wg genkey > /etc/lalune/wg-private.key; wg pubkey < /etc/lalune/wg-private.key > /etc/lalune/wg-public.key; fi
if [ ! -s /etc/lalune/gateway.json ]; then printf '%s\n' '{"Peer":"","Password":"","Hashes":"","Workers":9,"Obfs":"audio","Fingerprint":"chrome","ClientIDs":"8202606,6287487","CaptchaMode":"auto","VKAuthMode":"vkcalls","TurnTransport":"udp","TurnHost":"","TurnPort":"","DeviceID":"","WGPeerPublicKey":""}' > /etc/lalune/gateway.json; chmod 600 /etc/lalune/gateway.json; fi
systemctl daemon-reload
systemctl enable --now lalune-gateway.service
echo 'WG public key:'; cat /etc/lalune/wg-public.key
echo 'Panel token:'; cat /etc/lalune/panel.token 2>/dev/null || true
