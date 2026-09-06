# LGHS Bluetooth Zero-Touch Bootstrap

LGHS uses Bluetooth only for the first authenticated provisioning transaction of a stock Student Pi. Normal telemetry, commands, sudo state, release delivery, and audit traffic use the HTTPS Fleet plane.

Bluetooth is treated as an untrusted carrier. The first session is authenticated with a short-lived, password-derived **per-device bootstrap credential**, not a Fleet API token.

## Enrollment order

1. LGCSCONT advertises the provisioning RFCOMM service.
2. A fresh student participates only while Bluetooth bootstrap is explicitly enabled and no completion marker exists.
3. Student and controller create fresh nonces and ephemeral X25519 key pairs.
4. The student proves possession of its per-device bootstrap credential with an HMAC transcript proof.
5. LGCSCONT proves possession of the same bootstrap credential back to the student.
6. Both sides derive the AES-GCM session key with X25519 + HKDF-SHA256.
7. LGCSCONT sends the active Wi-Fi profile, controller SSH public key, and per-device Cloudflare tunnel bootstrap material inside authenticated ciphertext.
8. The student installs Wi-Fi, controller SSH authorization, and its outbound Cloudflare tunnel.
9. The student returns its Cloudflare hostname and Ed25519 SSH host key through the authenticated session.
10. LGCSCONT pins that identity and verifies SSH through Cloudflare.
11. Only after Cloudflare SSH verification does LGCSCONT mint a per-device Fleet API token.
12. The Fleet token is delivered inside the existing authenticated/encrypted Bluetooth session.
13. The student installs its Fleet identity and starts the agent, executor, policy, and timers.
14. The student reports `fleet-ready`, but this is not yet the controller success boundary.
15. LGCSCONT waits until `/var/lib/lghs/fleet.db` contains a fresh authenticated report for the expected device identity.
16. LGCSCONT records the `first-telemetry` milestone and only then consumes the one-time bootstrap credential.
17. Full classroom readiness is evaluated separately with `lghs-classroom-ready DEVICE`.

A Fleet API token is never used to establish the first Bluetooth session.

## Security properties

- Bootstrap proofs bind controller ID, device ID, both nonces, and both ephemeral public keys.
- Wi-Fi credentials and Cloudflare tunnel tokens are never placed in Bluetooth advertisements or sent as plaintext RFCOMM data.
- Ephemeral X25519 keys provide session forward secrecy; HKDF derives the session key and AES-GCM provides confidentiality/integrity.
- The Cloudflare tunnel token is held in controller memory only long enough to encrypt the authenticated provisioning payload.
- The student's SSH host key is returned through the authenticated Bluetooth session, then pinned before controller SSH verification.
- Fleet credentials are created only after controller-verified Cloudflare SSH succeeds.
- The bootstrap credential is retained if the first authenticated Fleet report is not observed, allowing safe retry.
- Existing enrolled students are not automatically opted into Bluetooth reprovisioning by a normal software update.

## Initial Wi-Fi support

The bootstrap implementation supports open Wi-Fi, WPA-PSK, and WPA3-SAE. 802.1X/EAP profiles are intentionally rejected rather than moving certificate/private-key material through this bootstrap transaction.

## Stock-device requirements

The preferred path is [`../bootstrap/STOCK-SETUP.md`](../bootstrap/STOCK-SETUP.md). LGCSCONT must be armed with the stock bootstrap secret before the fresh students start enrollment. No Fleet token is copied to a fresh Pi in advance.

LGCSCONT also requires its normal Cloudflare account/zone configuration and controller Fleet SSH identity. The student creates its local identity and derives its bootstrap credential before Bluetooth begins.

## Completion and runtime separation

The controller registry records:

```json
["bluetooth","cloudflare","cloudflare-verified","fleet","first-telemetry"]
```

After provisioning, Bluetooth bootstrap is one-shot and normal operation moves to HTTPS Fleet plus explicit Cloudflare SSH recovery. `lghs-classroom-ready DEVICE` is the final acceptance gate; Bluetooth success by itself is not classroom readiness.

Custom-image tooling under `image-builder/` is optional/legacy and is not the production identity/bootstrap model.