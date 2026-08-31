# LGHS Bluetooth Zero-Touch Bootstrap v2

LGHS 0.6 uses Bluetooth only for the first authenticated bootstrap of a freshly flashed Student Pi. Normal telemetry, commands, sudo state and audit traffic remain on the HTTPS fleet plane. The same authenticated/encrypted Bluetooth transaction now provisions both Wi-Fi and the device's Cloudflare SSH tunnel, so a fresh Student Pi does not require local SSH enrollment.

## Lifecycle

1. The controller keeps `lghs-bt-provision.service` available on RFCOMM channel 17 and advertises the alias `LGHS-PROVISION-<controller>`.
2. A fresh student image participates only when `/etc/lghs/bluetooth-bootstrap-enabled` exists and `/var/lib/lghs/bootstrap/wifi-provisioned.json` does not.
3. The student waits for controller Bluetooth discovery events.
4. Both sides create ephemeral X25519 keys and fresh nonces.
5. The student proves possession of its device-specific Fleet API token. The controller verifies that token against `/etc/lghs/fleet-api-tokens.json`.
6. The controller proves possession of the same device-specific token back to the student.
7. Both sides derive a per-session key with X25519 + HKDF-SHA256.
8. The controller reads its active NetworkManager Wi-Fi profile.
9. For a normal bootstrap, the controller also creates or reuses `LGHS-<DEVICE>`, configures `ssh-<device>.<zone> -> ssh://localhost:22`, creates/updates the Cloudflare DNS record, and obtains the per-tunnel token.
10. Wi-Fi credentials and the Cloudflare tunnel token are sent only inside the authenticated AES-256-GCM provisioning payload.
11. The student creates a root-owned NetworkManager connection, brings Wi-Fi online, and verifies the Fleet API `/health` endpoint over HTTPS.
12. The student installs/starts `cloudflared` using the received token and waits for a registered tunnel connection.
13. The student returns its ED25519 SSH host public key and allocated Cloudflare hostname over the authenticated Bluetooth session.
14. The controller records the Cloudflare transport in `/etc/lghs/fleet.json` and pins the student's host key for the public hostname.
15. The controller sends a final `ready` acknowledgement. Only then does the student write `wifi-provisioned.json`; the systemd condition prevents future unsolicited bootstrap attempts.

## Security properties

- SSID/PSK values and Cloudflare tunnel tokens are never placed in Bluetooth advertisements.
- Wi-Fi and tunnel credentials are never sent in plaintext over RFCOMM.
- A nearby Bluetooth device cannot request credentials or a tunnel without a valid per-device Fleet API token.
- Fresh ephemeral X25519 keys give sessions forward secrecy even though authentication uses an existing device token.
- Authentication proofs bind controller ID, device ID, both nonces and both ephemeral public keys, preventing transcript replay/substitution.
- The Cloudflare tunnel token is captured in controller process memory only long enough to encrypt it into the authenticated bootstrap payload. It is not put in argv or the controller fleet registry.
- The student's SSH host key is returned through the already authenticated Bluetooth channel, avoiding trust-on-first-use over an untrusted LAN.
- Existing student Pis are **not** automatically opted into Bluetooth reprovisioning by a normal update.
- A successful bootstrap is one-shot. Reprovisioning requires an explicit administrator action to remove the completion marker and enable bootstrap again.
- The controller does not log Wi-Fi passwords, Fleet tokens, or Cloudflare tunnel tokens.

## Initial Wi-Fi support

The bootstrap implementation supports:

- open Wi-Fi
- WPA-PSK
- WPA3-SAE

802.1X/EAP profiles are intentionally rejected rather than copying certificate/private-key material over Bluetooth.

## Image-builder / Imager requirements

When a student image is built with `LGHS_IMAGE_BUILD=1`, the installer creates `/etc/lghs/bluetooth-bootstrap-enabled`. Before first boot, LGHS Imager must inject:

- the device ID / hostname provisioning files,
- a unique Fleet API token for that device,
- the controller fleet SSH public key needed for later management.

LGCSCONT must already have the same device/token entry in `/etc/lghs/fleet-api-tokens.json`. The controller also needs its Cloudflare API token and account/zone configuration before a fresh student is powered on.

## Runtime separation

Bluetooth discovery is bootstrap-only. Once `/var/lib/lghs/bootstrap/wifi-provisioned.json` exists, the student bootstrap service no longer starts. Runtime management then uses the Fleet API over HTTPS and the per-device Cloudflare SSH hostname recorded by the controller.
