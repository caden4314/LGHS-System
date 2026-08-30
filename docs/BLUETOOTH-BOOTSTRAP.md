# LGHS Bluetooth Wi-Fi Bootstrap v1

LGHS 0.5.1 adds an out-of-band Bluetooth bootstrap path for freshly flashed student Pis. It is **not** a replacement for the HTTPS fleet plane. Bluetooth is used only to obtain the controller's current Wi-Fi profile; normal telemetry, commands, sudo state and audit traffic remain HTTPS.

## Lifecycle

1. The controller keeps `lghs-bt-provision.service` available on RFCOMM channel 17 and advertises the alias `LGHS-PROVISION-<controller>`.
2. A student image participates only when `/etc/lghs/bluetooth-bootstrap-enabled` exists and `/var/lib/lghs/bootstrap/wifi-provisioned.json` does not.
3. The student scans for the controller every 15 seconds.
4. Both sides create ephemeral X25519 keys and fresh nonces.
5. The student proves possession of its device-specific Fleet API token. The controller verifies that token against `/etc/lghs/fleet-api-tokens.json`.
6. The controller proves possession of the same device-specific token back to the student.
7. Both sides derive a per-session key with X25519 + HKDF-SHA256.
8. The controller reads the currently active NetworkManager Wi-Fi profile and sends it only inside AES-256-GCM authenticated encryption.
9. The student creates a root-owned NetworkManager connection and brings it online.
10. The student verifies the Fleet API `/health` endpoint over HTTPS. Only then does it write `wifi-provisioned.json`; the systemd condition prevents future unsolicited Bluetooth reprovisioning.

## Security properties

- SSID/PSK values are never placed in Bluetooth advertisements.
- Wi-Fi secrets are never sent in plaintext over RFCOMM.
- A nearby Bluetooth device cannot request credentials without a valid per-device Fleet API token.
- Fresh ephemeral X25519 keys give sessions forward secrecy even though authentication uses an existing device token.
- Authentication proofs bind controller ID, device ID, both nonces and both ephemeral public keys, preventing transcript replay/substitution.
- Existing student Pis are **not** automatically opted into Bluetooth reprovisioning by a normal update.
- A successful student bootstrap is one-shot. Reprovisioning requires an explicit administrator action to remove the completion marker and enable bootstrap again.
- The controller logs only device IDs, Bluetooth addresses and success/failure state; it does not log Wi-Fi passwords or Fleet tokens.

## Initial Wi-Fi support

The bootstrap implementation supports:

- open Wi-Fi
- WPA-PSK
- WPA3-SAE

802.1X/EAP profiles are intentionally rejected for the first protocol revision rather than copying certificate/private-key material over Bluetooth.

## Image-builder integration

When a student image is built with `LGHS_IMAGE_BUILD=1`, the installer creates `/etc/lghs/bluetooth-bootstrap-enabled`. The future 1.0 flasher/enrollment workflow must also provision a device ID and a unique Fleet API token before first boot. The controller must already have the matching device/token entry.

## Runtime separation

Bluetooth discovery is bootstrap-only. Once `/var/lib/lghs/bootstrap/wifi-provisioned.json` exists, the student bootstrap service no longer starts. Runtime fleet management continues to use `fleet-api.scenicrouteservers.com` over HTTPS.
