# LaLune NanoPi Gateway

LaLune is isolated from the existing NanoPi transports.

Owned resources: csqtt0, lalune-wg, routing table 200, ip rule priority 22000, NAT chain LALUNE_POST, UDP 51821 and panel 18787.

The main routing table, /etc/resolv.conf, xray0, 3x-ui, HydraRoute and Tailscale are not changed.

Path: Keenetic policy -> WireGuard -> lalune-wg -> table 200 -> csqtt0 -> CSQTT/VK TURN.

Keenetic WireGuard endpoint: 192.168.4.26:51821. Tunnel subnet: 10.77.0.0/30. Keenetic address: 10.77.0.2.
