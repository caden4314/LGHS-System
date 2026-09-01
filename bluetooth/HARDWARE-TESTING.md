# LGHS Bluetooth Zero-Touch Hardware Acceptance

Pre-release hardware validation only. Use the authorized test pair:

- Controller: `LGCSCONT`
- Student: `CS-999`

Do not mass-deploy or promote this branch from this test.

## Acceptance rule

A valid zero-touch pass starts from a freshly flashed CS-999 card with no manually configured Wi-Fi. Do not SSH into the student or manually create a NetworkManager profile to help the test succeed.

The intended sequence is:

1. First boot consumes the Imager provisioning files.
2. First boot creates unique SSH host keys and installs the per-device Fleet API token.
3. `lghs-bt-bootstrap.service` starts only after firstboot identity is ready.
4. CS-999 discovers LGCSCONT over Bluetooth.
5. Controller and student mutually authenticate using the CS-999 per-device token and ephemeral X25519 session keys.
6. Wi-Fi/tunnel provisioning payload is transferred only inside AES-GCM ciphertext.
7. CS-999 creates the NetworkManager Wi-Fi connection and reaches the Fleet API.
8. The pinned/verified Cloudflare connector is installed when needed and the student-specific tunnel token is applied.
9. Controller finalization completes and CS-999 becomes reachable through the managed transport.

## Before flashing

On LGCSCONT:

```bash
sudo systemctl status bluetooth.service --no-pager
sudo systemctl status lghs-bt-prepare.service --no-pager
sudo systemctl status lghs-bt-provision.service --no-pager
sudo test -s /etc/lghs/fleet-api-tokens.json && echo 'Fleet token registry: OK'
sudo visudo -c
```

Confirm CS-999 has a per-device token in the controller registry without printing the token:

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

## Observe LGCSCONT during first boot

```bash
sudo journalctl -fu lghs-bt-provision.service
```

In a second controller terminal:

```bash
watch -n 2 'systemctl --no-pager --full status bluetooth.service lghs-bt-provision.service | sed -n "1,35p"'
```

## Student checks after zero-touch completes

Only after the automatic sequence has completed and CS-999 is reachable:

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
  -b --no-pager > /tmp/lghs-cs999-bootstrap.log
```

Do not include Fleet API tokens, Wi-Fi passwords, tunnel tokens, `/etc/lghs/secrets/*`, or `/etc/cloudflared/token` in shared logs.

## Pass criteria

The test is a pass only if all of these are true without manual Wi-Fi assistance:

- firstboot finishes successfully;
- unique SSH host keys exist and `sshd -t` succeeds;
- Bluetooth mutual-auth provisioning succeeds;
- Wi-Fi is connected by the bootstrap flow;
- Fleet agent becomes healthy/reachable;
- Cloudflare connector starts with the student-specific token;
- bootstrap state is one-shot and does not continually reprovision after success;
- no credentials appear in journal output;
- rebooting CS-999 does not repeat provisioning or break connectivity.
