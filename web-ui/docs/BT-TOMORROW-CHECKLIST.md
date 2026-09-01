# Bluetooth Zero-Touch Hardware Acceptance — CS-999

This checklist is intentionally limited to the controller and the designated test student Pi.

## Pre-flash controller checks

- `lghs-bt-provision.service` active.
- `bluetooth.service` active with controller RFCOMM compatibility override applied.
- Controller alias is advertising `LGHS-PROVISION-*` as expected.
- Fleet API token registry contains the freshly staged CS-999 device token.
- Controller Cloudflare API token exists and its permissions are sufficient to create/configure tunnels, retrieve a tunnel token, and create/update the required DNS record.
- Controller active Wi-Fi profile can be read by NetworkManager with the required secret.
- Existing CS-999 Cloudflare tunnel/DNS state is understood before reuse/replacement.

## Fresh image checks before boot

- Generic image contains no SSH host private keys.
- First boot runs `ssh-keygen -A` before `sshd -t`.
- `/etc/lghs/bluetooth-bootstrap-enabled` exists on the student image.
- `lghs-bt-bootstrap.service`, `lghs-bt-prepare.service`, Bluetooth, NetworkManager and SSH are enabled.
- Per-device Fleet API token is staged by Imager before first boot.
- No Wi-Fi PSK or Cloudflare account-level API credential exists in the generic image.

## Expected stage sequence

1. First boot consumes Imager identity/secrets.
2. SSH host keys are generated.
3. Bluetooth adapter comes up.
4. Student discovers controller.
5. RFCOMM connects.
6. Student proves knowledge of its per-device Fleet token.
7. Controller proves the same token and both sides derive the ephemeral session key.
8. Controller sends encrypted Wi-Fi profile and only the CS-999 remotely-managed tunnel token.
9. Student installs/activates Wi-Fi.
10. Student confirms Fleet API health.
11. Student installs/starts its Cloudflare tunnel.
12. Student sends SSH hostname + ED25519 host public key to controller.
13. Controller pins the host key and finalizes fleet registry state.
14. Controller sends `complete/ready`.
15. Student writes one-shot provisioning marker.

## Acceptance evidence

Capture:

- `journalctl -u lghs-firstboot-provision -b`
- `journalctl -u lghs-bt-prepare -b`
- `journalctl -u lghs-bt-bootstrap -b`
- controller `journalctl -u lghs-bt-provision --since ...`
- `systemctl status lghs-cloudflared`
- Fleet API device inventory and last-seen
- controller fleet registry record
- controller known-host entry
- successful Cloudflare SSH after provisioning

## Failure rule

Do not manually configure Wi-Fi or copy a tunnel token to make the acceptance test pass. A failure should preserve its stage/logs so the bootstrap workflow can be fixed and retested.
