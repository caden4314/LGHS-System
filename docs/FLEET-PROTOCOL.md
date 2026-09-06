# LGHS Fleet Protocol v1

LGHS 0.6.0 uses an outbound HTTPS controller/student protocol for normal telemetry, commands, sudo state, audit transport, lifecycle evidence, and rollout health. Cloudflare SSH is an explicit administration/recovery path; it is not the passive liveness or command-delivery plane.

## Telemetry envelope

A managed student report uses protocol version 1 and carries a boot-scoped monotonic sequence:

```json
{
  "protocol": 1,
  "agent_version": "0.6.0",
  "device_id": "CS-999",
  "boot_id": "<uuid>",
  "sequence": 48291,
  "sent_at": 1788655000.0,
  "payload": {
    "metrics": {},
    "health": {},
    "health_report": {"health_version": 2, "checks": []},
    "command_states": [],
    "sudo_requests": [],
    "audit_batches": []
  }
}
```

`boot_id + sequence` is the ordering key. Sequence numbers increase within one boot and may reset only when `boot_id` changes.

## Controller response and delivery

The persistent agent uses:

- `POST /v1/report/<device>` for telemetry and state.
- `GET /v1/commands/<device>?wait=25` for bounded long-poll command delivery.

The controller persists authenticated telemetry in SQLite before compatibility views are refreshed. Fresh SQLite telemetry is therefore the authority for runtime liveness, provisioning milestones, and classroom acceptance.

## Command lifecycle and idempotency

Commands move through explicit execution states:

```text
QUEUED -> DELIVERED -> RECEIVED -> ACCEPTED -> RUNNING
                                      |          |
                                      |          +-> SUCCEEDED
                                      |          +-> FAILED
                                      |          +-> TIMED_OUT
                                      |          +-> REJECTED
                                      +------------> CANCELED when cancellation is still guaranteed
```

The controller may redeliver queued/delivered/received work. A command ID is also the device-side idempotency key, so redelivery does not create a second local side effect. Uncertain prior execution is held for explicit recovery rather than blindly repeated.

Human-readable stages such as `Fetching GitHub`, `Installing`, `Validating`, `Rolling back`, and `Reboot required` do not replace the execution state.

## Privilege boundary

```text
HTTPS Fleet API
      |
      v
lghs-agent (unprivileged)
  telemetry / long-poll / command state / audit cursors
      |
      | typed JSON over root-owned Unix socket
      v
lghs-command-executor (root)
  strict action allowlist / durable queue / typed helpers
```

The executor does not accept arbitrary shell text. Sensitive root operations are mapped to small validated actions such as exact-SHA update submission, release-key enrollment, typed reboot scheduling, and bounded status/audit reads.

## Signed exact-SHA updates

LGCSCONT is the revision authority. After the release verification public key is enrolled, a managed student exact-SHA update must include a canonical Ed25519-signed release manifest.

The signed payload binds at least:

```json
{
  "schema": 1,
  "release_sequence": 2,
  "channel": "main",
  "version": "0.6.0",
  "commit": "<40-character-git-sha>",
  "created_at": 1788655000,
  "expires_at": 1789259800,
  "minimum_updater": "0.6.0"
}
```

The student verifies signature, exact commit, channel, expiration, minimum updater version, and rollback sequence **before** Git/install work. The accepted release sequence is persisted only after successful target validation. Local-root emergency overrides are intentionally not exposed through Fleet.

## Structured health and liveness

`health_report.health_version = 2` contains typed checks with IDs, severity, observed/expected values, and remediation hints. Critical checks gate rollout/readiness; advisory warnings remain visible without automatically blocking deployment.

Important production checks include core services, root filesystem writability, disk space, clock synchronization, current undervoltage/throttling, controller transport freshness, sudo broker health, failed systemd units, and `release.signing-key`.

Operator liveness is grace-based rather than SSH-based:

```text
fresh telemetry -> OK/CHECK -> STALE -> OFFLINE
planned poweroff -> SHUTDOWN
planned reboot   -> REBOOTING -> new boot ID -> OK/CHECK
```

Planned lifecycle state is persisted and suppresses ordinary critical telemetry-loss alerts while it is authoritative.

## Sudo and audit transport

The root executor exposes sanitized sudo-request snapshots to the unprivileged agent. The controller stores request lifecycle in SQLite and approval/denial remains a typed administrator action.

Routine audit collection is also outbound HTTPS. Audit batches carry bounded file/inode/offset metadata and text; the controller acknowledges the highest accepted cursor before the student advances it. SSH audit sync remains an explicit recovery/backfill path.

## Controller state and durability

`/var/lib/lghs/fleet.db` is authoritative. SQLite runs with WAL, `synchronous=FULL`, foreign keys, and a bounded busy timeout. It contains device inventory, telemetry, commands/events, warnings, deployments/executions, lifecycle history, sudo state, audit events, notifications, and settings.

Controller backups use SQLite's online backup API and `PRAGMA quick_check`; a live WAL database is never backed up with a plain file copy.

## Provisioning boundary

Bluetooth does not carry a preexisting Fleet token. The controller first verifies Cloudflare SSH identity, then mints Fleet credentials. After the first authenticated Fleet report, LGCSCONT enrolls the release verification public key through the typed Fleet path and waits for fresh `release.signing-key` health before consuming the one-time bootstrap credential.

The final production acceptance authority is `lghs-classroom-ready DEVICE`, not Bluetooth completion or SSH reachability alone.

## Compatibility

Protocol version 1 intentionally remains stable across the 0.5-to-0.6 evolution. The 0.6 implementation accepts historical normalized command states where necessary, but new production behavior is defined by structured health v2, exact-SHA controller authority, signed releases, durable lifecycle history, and SQLite-backed command state.

Legacy JSON files may remain export/compatibility surfaces. They are not authoritative writers.
