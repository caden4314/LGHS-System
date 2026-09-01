# LGHS Full Project Pass — Web UI Integration Review

Date: 2026-08-31

This pass reviews the existing LGHS 0.6 architecture as the system the web UI must manage, rather than treating the dashboard as a separate frontend project.

## Existing system boundaries

### Student managed agent

`student/lghs-agent` is the primary network-facing process. It reports every ~5 seconds, long-polls commands, carries command milestones, sudo request snapshots and audit batches, and asks the privileged local executor for typed status/actions.

Current metrics include CPU percentage, memory percentage, root disk percentage, inode usage, root read-only status, temperature, load1 and Wi-Fi signal. Structured health includes services, temperature, memory, disk, filesystem writability, inode pressure, clock synchronization, undervoltage/throttling, reboot-required, failed systemd units, weak Wi-Fi, and controller transport freshness.

Important gap: the existing responsive CLI expects RX/TX counters/rates but `lghs-agent.metrics()` does not currently report them.

### Privileged local executor

`student/lghs-command-executor` is the privilege boundary for remote actions. The web UI should never bypass it by inventing direct SSH command execution. New remote actions should become typed command-plane operations with validation, state transitions and audit.

### Fleet API/controller

`controller/lghs-fleet-api` owns device authentication, latest telemetry, command delivery, inventory, groups, tags, deployments, recovery, maintenance and scheduled reboots. It already has a strong SQLite WAL state model.

Current API gap for the web UI: admin endpoints expose devices, groups, deployments, maintenance and reboots, but not first-class read APIs for warnings, audit/activity, current sudo requests or historical telemetry. The first UI gateway can normalize the existing cache for read-only preview, but the durable solution is to add explicit Fleet API resources.

### Database

The database already contains devices, latest telemetry, commands/events, warnings/events, deployments/executions, sudo requests, audit events, notifications and settings. It stores only the latest telemetry payload, so historical charts require a new bounded history/rollup schema rather than browser-generated history.

### Current terminal UI

The responsive curses UI has useful operational concepts that should survive the web migration: fleet status, cache freshness, telemetry, sudo review, updates, logs, notices, groups/tags and device-focused operations. The web UI should replace presentation/navigation, not regress these workflows.

### Updates

The update design uses exact Git commit targets, staged deployment executions, health convergence, recovery/rollback and desired state. The web UI must preserve immutable target commit visibility and should never reduce an update to a generic progress spinner.

### First boot / image

`student/lghs-firstboot-provision` consumes boot-partition configuration, provisions account passwords, device identity, Fleet API identity and deployment SSH identity, then removes secrets. The image-build-specific SSH host key fix developed locally must remain part of the final release image: generic images must not carry reusable SSH host private keys, and first boot must generate them before `sshd -t`.

### Bluetooth bootstrap

The current protocol uses a per-device Fleet token for mutual application authentication, ephemeral X25519, HKDF and AES-GCM. Controller sends active Wi-Fi plus a device-specific Cloudflare tunnel token only after authentication.

Must-fix discovered in this review: the student's Bluetooth systemd sandbox currently blocks the Cloudflare installer's required writes to `/etc/cloudflared`, `/etc/systemd/system`, and potentially `/usr/local/bin`.

Transport recommendation: keep RFCOMM for the immediate hardware acceptance test once lifecycle issues are fixed. Build a GATT/LE advertisement transport as a protocol-v2-compatible transport later, preserving the existing application crypto and message semantics.

### Cloudflare

The controller owns the broad Cloudflare API credential and creates/reuses one remotely managed tunnel per student. Student receives only its tunnel token. This is the correct direction: never place the account-level Cloudflare API token on a student Pi.

The future web UI gets a separate tunnel and hostname. Its browser authentication is Cloudflare Access; the origin independently validates the signed Access JWT and applies LGHS roles.

## Web UI implications

1. **No browser-to-Pi SSH for dashboard rendering.** Browser -> web gateway -> Fleet API/cache/database.
2. **No admin token in browser.** Gateway holds controller-local admin authority.
3. **No fake production telemetry.** Missing history remains missing.
4. **Every write becomes an audited typed operation.** Reboot, maintenance, tags, deployments, rollback, sudo, etc.
5. **Fleet table is primary.** Device pages are drill-downs; overview is an exception/attention surface.
6. **Provisioning gets a future first-class section.** It should expose firstboot/BT/Wi-Fi/Fleet/tunnel/SSH stages rather than a single `ready` boolean.
7. **Telemetry history belongs to the controller data plane.** Bounded retention and server-side downsampling.
8. **UI health is derived from authoritative structured health when available.** Browser threshold duplication is temporary only.

## Highest-priority engineering work before first hosted test

1. Remove synthetic telemetry history from production device pages.
2. Add a trustworthy controller-status state; never hardcode `online` in the shell.
3. Make session/login failure UX intentional and Cloudflare Access-aware.
4. Add real alerts/sudo/activity read endpoints or explicitly mark those sections unavailable until wired.
5. Add network counters to the agent and normalize rates at the controller.
6. Add bounded telemetry history storage/query API.
7. Wire SSE invalidation/events after the read model is stable.
8. Add role-aware action surfaces with confirmations, CSRF, audit and idempotency.
9. Add provisioning/tunnel status only after tomorrow's BT lifecycle is verified.
10. Keep UI deployment isolated from the 0.6 image/update release until hardware acceptance.
