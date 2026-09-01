# LGHS Bluetooth Zero-Touch Hardware Acceptance

Pre-release validation only.

- Controller: `LGCSCONT`
- Tonight live student test: `CS-999`
- First fresh class flash tomorrow: `CS-01`

Do not mass-deploy or promote this branch from the CS-999 live test alone.

## Two different tests

### Tonight: live CS-999 validation

CS-999 is **not reflashed**. Use it to validate the hardened Bluetooth service lifecycle, the controller Cloudflare credential, per-device tunnel creation/update, encrypted Bluetooth exchange, and service behavior on an already-running LGHS student.

Install the branch on LGCSCONT and CS-999 with `bluetooth/install-live-test.sh`. Installation alone preserves the existing `/var/lib/lghs/bootstrap/wifi-provisioned.json` marker and will not trigger a new Wi-Fi provisioning cycle.

Only when intentionally testing the full BT flow on CS-999, use the explicit `--rearm` option on CS-999. The installer backs up the prior provisioning marker before removing it. This can re-apply Wi-Fi and the CS-999 Cloudflare tunnel, so do not use `--rearm` accidentally.

### Tomorrow: fresh CS-01 class acceptance

The valid fresh zero-touch acceptance starts from a newly flashed CS-01 card with no manually configured Wi-Fi. Do not SSH into CS-01 or manually create a NetworkManager profile to help the test succeed.

The intended sequence is:

1. First boot consumes the Imager provisioning files.
2. First boot creates unique SSH host keys and installs the per-device Fleet API token.
3. `lghs-bt-bootstrap.service` starts only after firstboot identity is ready.
4. CS-01 discovers LGCSCONT over Bluetooth.
5. Controller and student mutually authenticate using the CS-01 per-device token and ephemeral X25519 session keys.
6. Wi-Fi/tunnel provisioning payload is transferred only inside AES-GCM ciphertext.
7. CS-01 creates the NetworkManager Wi-Fi connection and reaches the Fleet API.
8. The pinned/verified Cloudflare connector is installed when needed and the student-specific tunnel token is applied.
9. Controller finalization completes and CS-01 becomes reachable through the managed transport.

## Tonight: prepare LGCSCONT

After pulling the BT PR branch:

```bash
sudo bash ./bluetooth/install-live-test.sh --start
```

The installer also runs the safe read-only Cloudflare credential probe. You can repeat it without exposing the token:

```bash
sudo /usr/local/sbin/lghs-cloudflare-token-check
```

Confirm services and Fleet registry health:

```bash
sudo systemctl status bluetooth.service --no-pager
sudo systemctl status lghs-bt-prepare.service --no-pager
sudo systemctl status lghs-bt-provision.service --no-pager
sudo test -s /etc/lghs/fleet-api-tokens.json && echo 'Fleet token registry: OK'
sudo visudo -c
```

Confirm CS-999 has a per-device Fleet token without printing it:

```bash
sudo python3 - <<'PY'
import json
from pathlib import Path
p = Path('/etc/lghs/fleet-api-tokens.json')
data = json.loads(p.read_text())
entry = data.get('devices', {}).get('CS-999') if isinstance(data, dict) else None
print('CS-999 token registry:', 'OK' if entry else 'MISSING')
PY
```

## Tonight: install on CS-999 without re-provisioning

After pulling the BT PR branch on CS-999:

```bash
sudo bash ./bluetooth/install-live-test.sh
```

This installs/enables the hardened files but intentionally preserves the existing provisioned state.

When ready for the deliberate live Bluetooth reprovision test:

```bash
sudo bash ./bluetooth/install-live-test.sh --rearm
```

At the same time on LGCSCONT:

```bash
sudo journalctl -fu lghs-bt-provision.service
```

On CS-999 in a second terminal if its current SSH path remains available:

```bash
sudo journalctl -fu lghs-bt-bootstrap.service
```

## Tomorrow: preflight for CS-01

Before flashing CS-01, confirm the controller is ready and CS-01 has been enrolled by the Imager with a per-device Fleet token. Check presence without printing the token:

```bash
sudo python3 - <<'PY'
import json
from pathlib import Path
p = Path('/etc/lghs/fleet-api-tokens.json')
data = json.loads(p.read_text())
entry = data.get('devices', {}).get('CS-01') if isinstance(data, dict) else None
print('CS-01 token registry:', 'OK' if entry else 'MISSING')
PY
```

Observe LGCSCONT during CS-01 first boot:

```bash
sudo journalctl -fu lghs-bt-provision.service
```

In a second controller terminal:

```bash
watch -n 2 'systemctl --no-pager --full status bluetooth.service lghs-bt-provision.service | sed -n "1,35p"'
```

## Student checks after zero-touch completes

Only after the automatic sequence has completed and the student is reachable:

```bash
sudo systemctl status lghs-firstboot-provision.service --no-pager
sudo systemctl status lghs-bt-bootstrap.service --no-pager
sudo systemctl status NetworkManager.service --no-pager
sudo systemctl status lghs-agent.service --no-pager
sudo systemctl status lghs-cloudflared.service --no-pager
```

Verify unique host keys exist:

```bash
sudo ls -l /etc/ssh/ssh_host_*_key /etc/ssh/ssh_host_*_key.pub
sudo sshd -t && echo 'sshd config: OK'
```

Verify bootstrap state without exposing secrets:

```bash
sudo test -s /etc/lghs/secrets/fleet-api-token && echo 'Fleet token: present'
sudo test -f /var/lib/lghs/bootstrap/wifi-provisioned.json && echo 'Wi-Fi bootstrap: complete'
sudo test -f /var/lib/lghs/provisioned && echo 'Firstboot: complete'
```

Network/Fleet checks:

```bash
nmcli -t -f GENERAL.STATE,GENERAL.CONNECTION device show wlan0
ip route
sudo /usr/local/sbin/lghs-report summary 2>/dev/null || true
```

Cloudflare connector version/hash check when `/usr/local/bin/cloudflared` is installed:

```bash
/usr/local/bin/cloudflared --version
sha256sum /usr/local/bin/cloudflared
```

For the pinned ARM64 2026.8.1 test build, expected SHA-256 is:

```text
6d517efc10dfce17440177bd7011909166eab44bae0f6998182183df717c7dba
```

## Logs to capture on any failure

Controller:

```bash
sudo journalctl -u bluetooth.service -u lghs-bt-prepare.service -u lghs-bt-provision.service -b --no-pager > /tmp/lghs-controller-bt.log
```

Student:

```bash
sudo journalctl \
  -u lghs-firstboot-provision.service \
  -u bluetooth.service \
  -u lghs-bt-prepare.service \
  -u lghs-bt-bootstrap.service \
  -u NetworkManager.service \
  -u lghs-cloudflared.service \
  -u lghs-agent.service \
  -b --no-pager > /tmp/lghs-student-bootstrap.log
```

Do not include Fleet API tokens, Wi-Fi passwords, tunnel tokens, `/etc/lghs/secrets/*`, or `/etc/cloudflared/token` in shared logs.

## Fresh CS-01 pass criteria

The first class zero-touch test is a pass only if all of these are true without manual Wi-Fi assistance:

- firstboot finishes successfully;
- unique SSH host keys exist and `sshd -t` succeeds;
- Bluetooth mutual-auth provisioning succeeds;
- Wi-Fi is connected by the bootstrap flow;
- Fleet agent becomes healthy/reachable;
- Cloudflare connector starts with the CS-01-specific token;
- bootstrap state is one-shot and does not continually reprovision after success;
- no credentials appear in journal output;
- rebooting CS-01 does not repeat provisioning or break connectivity.
