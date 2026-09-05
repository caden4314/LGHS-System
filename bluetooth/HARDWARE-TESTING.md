# LGHS Bluetooth / Stock-OS Hardware Acceptance

This document describes the current classroom path: stock Raspberry Pi OS, password-derived Bluetooth bootstrap, controller-verified Cloudflare SSH, then Fleet enrollment.

The older custom-image flow that installed a Fleet token before Bluetooth is obsolete and must not be used for fresh classroom devices.

## Required topology

- Controller: `LGCSCONT`
- Student devices: `CS-01`, `CS-02`, ... with matching users `cs-01`, `cs-02`, ...
- Student management user: `cs-admin`
- Runtime management: HTTPS Fleet plane plus per-device Cloudflare SSH
- Bluetooth: bootstrap only

## Non-negotiable enrollment order

1. Student boots stock Raspberry Pi OS and has Internet access.
2. `bootstrap/install-stock.sh` installs LGHS without starting Fleet.
3. Student and controller mutually authenticate using the password-derived per-device bootstrap credential.
4. Bluetooth transfers Cloudflare bootstrap data and the controller SSH public key inside the encrypted session.
5. Student brings up its per-device Cloudflare tunnel.
6. LGCSCONT verifies SSH through the Cloudflare hostname using the controller key.
7. Only after that proof does LGCSCONT mint and send the per-device Fleet token.
8. Student starts Fleet agent, command executor, and policy services.
9. Bootstrap credential is consumed and Bluetooth bootstrap becomes permanently inactive.

If Fleet starts before step 6 succeeds, the test fails.

## Controller preflight

Arm credentials for the classroom set:

```bash
sudo python3 /opt/lghs/repo/controller/lghs-stock-bootstrap-secret
sudo python3 /opt/lghs/repo/controller/lghs-stock-bootstrap-secret --status
```

No arguments arm `CS-01` through `CS-14` for 30 days. Use `--device CS-##` to re-arm one device.

Confirm controller services:

```bash
systemctl is-active bluetooth.service lghs-bt-prepare.service lghs-bt-provision.service lghs-fleet-api.service
systemctl --failed --no-pager
```

Do not print Cloudflare tokens, Fleet tokens, bootstrap credentials, or the derived master during testing.

## Fresh student acceptance

Flash Raspberry Pi OS Desktop 64-bit with hostname `CS-##`, matching student user `cs-##`, working Internet Wi-Fi, and SSH enabled. Do not manually create `cs-admin`.

Run locally as the student:
```bash
curl -fsSL https://raw.githubusercontent.com/caden4314/LGHS-System/main/bootstrap/install-stock.sh -o /tmp/lghs-stock.sh && sudo bash /tmp/lghs-stock.sh
```

Enter the same provisioning password armed on LGCSCONT. After the installer says zero-touch provisioning started, leave the Pi powered on near the controller.

Watch the controller:

```bash
sudo journalctl -fu lghs-bt-provision.service
```

Required final controller evidence:

```text
Cloudflare VERIFIED CS-##: cs-admin@ssh-cs-##.scenicrouteservers.com
READY CS-##: Bluetooth -> Cloudflare verified -> Fleet enrolled
```

Then verify the student's provision record includes this exact order:

```json
["bluetooth","cloudflare","cloudflare-verified","fleet"]
```

`lghs-bt-bootstrap.service` being inactive after `READY` is expected.
## Student validation

Run on the student or through Fleet:

```bash
sudo /usr/local/sbin/lghs-check
systemctl --failed --no-pager
getent passwd cs-## cs-admin cs_admin lg_cs_cont
systemctl is-active lghs-cloudflared.service lghs-agent.service lghs-command-executor.service lghs-policy.service
systemctl is-enabled lghs-update.timer
```

Required result:

- every `lghs-check` item passes
- zero failed systemd units
- only the canonical `cs-##` and `cs-admin` human identities remain
- Cloudflare, agent, executor, and policy are active
- update timer is enabled
- no persistent network queue work remains

## Fleet command acceptance

Queue an LGHS update from the controller and verify the device reports the exact target commit after execution. A successful command response alone is not enough; telemetry must converge to the target SHA.

Duplicate delivery of the same command must not enqueue or execute the local update twice.
## Fleet sudo acceptance

Use the built-in noninteractive self-test from the controller:

```text
sudo-test CS-##
sudo-list CS-##
sudo-approve CS-## REQUEST_ID
sudo-test-status CS-##
```

Approval passes only when the final self-test log contains root identity output and the request reaches `completed`.

Also test denial on a separate request:

```text
sudo-test CS-##
sudo-deny CS-## REQUEST_ID
sudo-test-status CS-##
```

A denied request must stop without executing the privileged command.

## Update / reconcile stability

An already-current update must be non-disruptive. Capture controller runtime state before and after a no-op update:

```text
controller-runtime
update-controller
controller-runtime
```
For healthy Fleet services, PID, restart count, invocation ID, and start timestamp must remain unchanged across the no-op updater run.

Post-update validation is fail-closed: if `lghs-check` or a required service validation fails, the updater must not record the target as successfully installed.

## Current classroom rollout gate

Do not mass-deploy the next student set until all of these are true on the current runtime commit:

- all three GitHub validation workflows are green
- LGCSCONT is healthy on the same validated runtime
- at least one fresh stock student completed Bluetooth -> Cloudflare verification -> Fleet in the required order
- a second fresh stock student has clean canonical identities and passes `lghs-check`
- Fleet command delivery has updated a student to the expected exact commit
- Fleet sudo approval has executed the test command only after approval
- Fleet sudo denial has prevented execution
- no-op controller updates do not restart healthy Fleet services
- there are no pending network-queue jobs or sudo requests

Power-loss, rollback, phased rollout, structured-health, and scheduled-reboot release-candidate tests remain tracked separately in `docs/0.6-RC-HARDWARE-VALIDATION.md` and should not be inferred from this bootstrap acceptance.
