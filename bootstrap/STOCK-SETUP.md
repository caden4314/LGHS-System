# LGHS Stock Raspberry Pi OS Deployment

This is the preferred classroom deployment path when building a custom pi-gen image is not desirable.

## Required order

LGHS intentionally enforces this enrollment order:

1. Stock Raspberry Pi OS boots with a `cs-##` student account.
2. Local LGHS bootstrap installs the software and creates `cs-admin`.
3. A one-time bootstrap credential authenticates the Bluetooth exchange.
4. Bluetooth delivers Wi-Fi/Cloudflare bootstrap data and the controller SSH public key.
5. The student starts its per-device Cloudflare tunnel.
6. LGCSCONT verifies SSH to the device through the Cloudflare hostname.
7. Only after that verification does LGCSCONT mint a per-device Fleet API token.
8. The Fleet token is delivered over the already authenticated/encrypted Bluetooth session.
9. Fleet services and LGHS policy enforcement are enabled.

A Fleet token is never required to establish the first Bluetooth session.

## Raspberry Pi Imager settings

For `CS-01` use Raspberry Pi OS Desktop 64-bit and set:

- hostname: `CS-01`
- username: `cs-01`
- Wi-Fi: the network that gives the Pi Internet access
- SSH: enabled

Repeat the naming rule for each device (`CS-02` / `cs-02`, etc.).

## Run on the freshly booted Pi

Open a terminal while logged in as the `cs-##` student account:

```bash
curl -fsSL https://raw.githubusercontent.com/caden4314/LGHS-System/main/bootstrap/install-stock.sh -o /tmp/lghs-stock.sh
sudo bash /tmp/lghs-stock.sh
```

The installer asks for the teacher password used by `cs-admin` and Root. It then installs the complete LGHS payload but intentionally leaves Fleet services dormant.

At the end it prints a one-time Bluetooth bootstrap token. The token expires after 24 hours and is deleted from the controller registry after successful enrollment.

## Register the one-time token from the Windows manager

First update LGCSCONT so it has the Bluetooth-before-Fleet implementation:

```powershell
ssh LGCSCONT-CF "sudo /usr/local/sbin/lghs-update"
ssh LGCSCONT-CF "sudo systemctl restart lghs-bt-provision.service"
```

Then register the token printed by the Pi. For example, for `CS-01`:

```powershell
$bt = '<TOKEN_PRINTED_BY_CS-01>'
$bt | ssh LGCSCONT-CF "sudo python3 /opt/lghs/repo/controller/lghs-bootstrap-enroll CS-01"
Remove-Variable bt
```

Do **not** run `lghs-imager-enroll` and do not manually create a Fleet token for the stock bootstrap path.

## Watch enrollment

Controller:

```powershell
ssh LGCSCONT-CF "sudo journalctl -fu lghs-bt-provision.service"
```

Student Pi:

```bash
sudo journalctl -fu lghs-bt-bootstrap.service
```

Successful controller output ends with messages similar to:

```text
Cloudflare VERIFIED CS-01: cs-admin@ssh-cs-01.scenicrouteservers.com
READY CS-01: Bluetooth -> Cloudflare verified -> Fleet enrolled
```

## Verify the student

After enrollment:

```bash
cat /etc/lghs/student-user
cat /etc/lghs/admin-user
cat /var/lib/lghs/bootstrap/wifi-provisioned.json
systemctl is-active lghs-cloudflared.service
systemctl is-active lghs-agent.service
systemctl is-active lghs-command-executor.service
systemctl is-active lghs-policy.service
```

Expected account files are `cs-01` (or that device's number) and `cs-admin`.

The stock installer configures a persistent Git checkout filter and `/etc/lghs/update.env`, so later `lghs-update` runs retain the per-device `cs-##`/`cs-admin` account mapping even though legacy custom-image source still uses `lg_cs_cont`/`cs_admin` defaults upstream.
