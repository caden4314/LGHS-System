# LGHS Stock Raspberry Pi OS Deployment

This is the preferred classroom deployment path. It starts from stock Raspberry Pi OS and does not require a custom image.

## Required order

LGHS enforces this enrollment order:

1. Stock Raspberry Pi OS boots with hostname `CS-##` and student user `cs-##`.
2. The local stock installer creates `cs-admin` and installs LGHS with Fleet services still dormant.
3. The student derives a per-device one-time Bluetooth credential from the teacher provisioning password.
4. The controller validates that credential and sends Cloudflare bootstrap data plus its SSH public key over the authenticated/encrypted Bluetooth session.
5. The student starts its per-device Cloudflare tunnel.
6. LGCSCONT verifies SSH through that Cloudflare hostname using the controller key.
7. Only after successful Cloudflare SSH verification does LGCSCONT mint a per-device Fleet API token.
8. The Fleet token is delivered over the existing authenticated/encrypted Bluetooth session.
9. Fleet services and LGHS policy enforcement start, and the bootstrap credential is consumed.

A Fleet token is never used to establish the first Bluetooth session.

## Raspberry Pi Imager settings

For `CS-01`, use Raspberry Pi OS Desktop 64-bit and set:

- hostname: `CS-01`
- username: `cs-01`
- Wi-Fi: the school/guest network that provides Internet access
- SSH: enabled

Repeat the naming rule for every device (`CS-02` / `cs-02`, and so on).

## Arm the controller once

On LGCSCONT, arm the classroom device credentials before starting the Pis:

```bash
sudo python3 /opt/lghs/repo/controller/lghs-stock-bootstrap-secret
```

With no arguments this arms `CS-01` through `CS-14` for 30 days. Enter the provisioning password twice. The controller stores only a derived master and per-device derived credentials, never the plaintext password.

Check status without exposing credentials:

```bash
sudo python3 /opt/lghs/repo/controller/lghs-stock-bootstrap-secret --status
```
Re-arm only one device when needed:

```bash
sudo python3 /opt/lghs/repo/controller/lghs-stock-bootstrap-secret --device CS-07
```

A successful Fleet handoff consumes that device's controller registry credential.

## Run on each freshly booted student Pi

Log in locally as the matching `cs-##` account and run:

```bash
curl -fsSL https://raw.githubusercontent.com/caden4314/LGHS-System/main/bootstrap/install-stock.sh -o /tmp/lghs-stock.sh && sudo bash /tmp/lghs-stock.sh
```

Enter the same provisioning password that was armed on LGCSCONT. The same password is also set for `cs-admin` and Root on that Pi.

When the installer finishes, leave the Pi powered on near LGCSCONT. No token copy, Windows command, or manual Fleet enrollment is required.

## Watch enrollment

Controller:

```bash
sudo journalctl -fu lghs-bt-provision.service
```
Student:

```bash
sudo journalctl -fu lghs-bt-bootstrap.service
```

Successful controller output ends with messages similar to:

```text
Cloudflare VERIFIED CS-01: cs-admin@ssh-cs-01.scenicrouteservers.com
READY CS-01: Bluetooth -> Cloudflare verified -> Fleet enrolled
```

The final provision record must preserve this order:

```json
["bluetooth","cloudflare","cloudflare-verified","fleet"]
```

After `READY`, `lghs-bt-bootstrap.service` becoming inactive is expected; bootstrap is one-shot.

## Verify the student

```bash
sudo /usr/local/sbin/lghs-check
systemctl --failed --no-pager
getent passwd cs-01 cs-admin cs_admin lg_cs_cont
cat /var/lib/lghs/bootstrap/wifi-provisioned.json
```
Expected identities on `CS-01` are only `cs-01` and `cs-admin`; legacy `cs_admin` / `lg_cs_cont` identities must not remain.

Verify managed services after enrollment:

```bash
systemctl is-active lghs-cloudflared.service lghs-agent.service lghs-command-executor.service lghs-policy.service
systemctl is-enabled lghs-update.timer
```

## Security properties

- Initial Bluetooth authentication uses the password-derived, per-device one-time credential; it is not a Fleet token.
- Session key exchange uses ephemeral X25519, HKDF, AES-GCM, and mutual HMAC transcript proofs.
- Fleet enrollment is blocked until LGCSCONT proves Cloudflare SSH reachability using its controller key.
- The student bootstrap token is removed after successful Fleet handoff.
- Controller registry credentials expire after 30 days and are consumed on successful enrollment.
- The stock Git identity filter preserves `cs-##` / `cs-admin` mappings for later updater runs while legacy source defaults are still being retired.
