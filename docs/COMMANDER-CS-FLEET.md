# LGHS CS Fleet — Commander enrollment and offline rollout readiness

Status reviewed **2026-10-22**. This document describes a staging plan, not a claim that the school controller or student Pis were modified remotely on this date.

## Current topology and enrollment gate

- **LGCSCONT** is the only LGHS release-signing authority and the preferred single Caden Commander management agent for the classroom fleet.
- **BARRACUDA** is the existing Caden Commander gateway; LGCSCONT was **not** listed among its enrolled or pending Commander agents in the 2026-10-22 check.
- **CS-999** is the canary; CS-01/02/03 are enrolled production students from the last documented LGHS acceptance. CS-04 through CS-14 require new device provisioning and must not be marked enrolled in advance.
- The current Commander Linux fleet installer under `cc-fleet-ui/installer/install-caden-commander-linux.sh` is explicitly **x86_64-only**. It must not be executed on an ARM64 Raspberry Pi. Before LGCSCONT can be enrolled, build and verify an ARM64 Commander agent release, then install it as an unprivileged systemd service on the controller, configure its outbound TLS gateway, and explicitly approve its pending identity on BARRACUDA. Never copy another agent's identity or bundle access credentials in this repository.
- Existing LGHS identity / Cloudflare SSH / Fleet API credentials are independent of Commander enrollment. Do not disable or replace existing LGHS authentication to make Commander connect.
- No classroom device should be made to execute a Commander bootstrap command merely because it received an LGHS update.

## Offline power-on update behavior

1. From the controller, authorize a **specific exact Git SHA** via the normal Fleet deployment interface. Do not enable autonomous Git branch tracking on students.
2. Deploy to **CS-999** first; require signed release verification, health checks, and real telemetry confirmation before advancing to other classroom devices.
3. The controller stores a queued update command for each dispatched Pi. Normal offline rollout commands have a **180-day deadline** unless an operator sets an explicit deadline; this covers students that are turned on at a later date.
4. The student `lghs-agent` reconnects over HTTPS automatically after networking becomes available. The controller supplies the exact SHA with a **fresh Ed25519 release manifest at delivery time**, so an old queued command does not carry a seven-day-old signature.
5. The unprivileged student agent sends the typed payload to `lghs-command-executor`, which persists the idempotent update into `lghs-netqueue`. Network failures are retried and the update's stage is reported to Fleet.
6. A paused or failed rollout requires operator handling; offline Pi catch-up is **not** permission to skip canary soak or health gates. Expired deployment commands must be reviewed and re-authorized; the next boot does not automatically select GitHub HEAD.
7. The Fleet admin API can distinguish `waiting_for_device` from `updating` when a target revision is pending but a Pi has not reported for more than 90 seconds.

## Live acceptance after LGCSCONT and CS-999 can be reached

Check LGCSCONT's role, release key, service health, Fleet device list, and its existing controller backup **without printing secrets**:

```bash
cat /etc/lghs/role
sudo systemctl is-active lghs-fleet-api.service lghs-rollout-manager.service
sudo systemctl is-enabled lghs-update.timer lghs-reconcile.timer
sudo lghsctl controller-runtime
sudo lghsctl release-status
sudo lghsctl health CS-999
sudo lghsctl classroom-ready CS-999
```

On CS-999, validate the agent, executor, and persistent queue; confirm both network loss and restoration and reboot recovery. During a planned canary update, verify the exact target, valid signed manifest, accepted execution, installed commit, and fresh health reports. Only then authorize other enrolled students to update on their next power-on.

Commander side acceptance: confirm LGCSCONT appears as **pending**, explicitly approve that genuine device in Caden Commander, verify the connection is persistent through restart, and scope remote commands to the controller rather than presenting offline student Pis as individual online Commander machines.

## Boundaries

- A green CI test does not replace the live hardware acceptance above.
- Do not turn off sudo approval, LGHS device auth, Cloudflare SSH trust, Ed25519 verification or staged rollout gates to force a deployment.
- The source implementation is on the `feat/lgcs-fleet-catchup-20261022` development branch until review/merge; updating the controller and canary is a **separate** operation.
