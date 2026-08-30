# LGHS Fleet Protocol v1

LGHS 0.5 formalizes the controller/student contract. Normal fleet operations use outbound HTTPS. Cloudflare SSH remains an explicit administration and recovery path, not the passive data plane.

## Telemetry envelope

Every 0.5 managed-agent report carries:

```json
{
  "protocol": 1,
  "agent_version": "0.5.0",
  "device_id": "CS-999",
  "boot_id": "...",
  "sequence": 48291,
  "sent_at": 1788068837.1,
  "payload": {
    "metrics": {},
    "health": {},
    "health_report": {"health_version": 1, "checks": []},
    "command_states": [],
    "sudo_requests": [],
    "audit_batches": []
  }
}
```

`boot_id + sequence` is the ordering key. Sequence numbers must increase within one boot and may reset after `boot_id` changes.

## Controller response

```json
{
  "protocol": 1,
  "received_at": 1788068837.2,
  "commands": [],
  "audit_ack": {}
}
```

## Command transport

The persistent agent uses two related HTTPS paths:

- `POST /v1/report/<device>` for telemetry, health, command state, sudo state and audit batches.
- `GET /v1/commands/<device>?wait=25` for bounded long-poll command delivery.

Long polling is capped below the Cloudflare request timeout and reconnects after completion/failure. Normal command latency therefore no longer depends on the regular telemetry interval.

The controller redelivers commands in `queued`, `delivered`, or `received` state until the device reaches `accepted`. Device-side local acceptance is idempotent by command ID.

## Command lifecycle

Execution state is independent from human-readable stage text.

```text
QUEUED
  -> DELIVERED
  -> RECEIVED
  -> ACCEPTED
  -> RUNNING
      -> SUCCEEDED
      -> FAILED
      -> TIMED_OUT
      -> REJECTED
      -> CANCELED
```

Examples of `stage` are `Fetching GitHub`, `Installing`, `Validating`, `Rolling back`, and `Reboot required`.

## Student privilege boundary

```text
Internet / Fleet API
        |
        v
lghs-agent (unprivileged lghs-agent user)
  - telemetry
  - long-poll
  - event wakeups
  - audit cursors
  - command state
        |
        | JSON over root-owned Unix socket
        v
lghs-command-executor (root)
  - strict action allowlist
  - update queue submission
  - sanitized service/hardware status
  - bounded audit reads
  - sanitized sudo-request snapshots
```

The executor never accepts shell text. Network commands map only to typed allowlisted operations.

## Sudo events

The root executor reads the protected request directory and returns a sanitized request snapshot to the unprivileged agent. The agent polls this local typed operation every second and wakes telemetry immediately when the snapshot changes. The controller stores request lifecycle in the SQLite `sudo_requests` table while continuing to expose the snapshot to existing Fleet Control compatibility views.

## Audit transport

Routine audit collection is outbound HTTPS rather than recurring controller SSH fan-out. The agent requests bounded chunks from the root executor and reports `{kind,inode,offset,next_offset,text}` batches. The controller persists them in `audit_events` and acknowledges the highest accepted offset. The endpoint only advances its cursor after acknowledgement.

`lghs-audit-sync` remains available as an explicit SSH recovery/backfill path.

## Health and warnings

The agent publishes a structured health schema plus Raspberry Pi metrics including CPU, memory, disk, inode usage, temperature, Wi-Fi signal, clock synchronization, reboot requirement, undervoltage and throttling flags. The controller projects failures into persistent warnings with `new`, `acknowledged`, and `resolved` lifecycle.

## Controller state

`/var/lib/lghs/fleet.db` is the 0.5 source of truth and runs SQLite in WAL mode. It contains devices, latest telemetry, commands, command events, warnings, warning events, deployments, deployment executions, sudo requests, audit events, notifications and settings.

Legacy JSON files remain compatibility/export surfaces during migration. They are not authoritative writers.

## Compatibility

During staged 0.4 -> 0.5 migration the controller accepts legacy telemetry and normalizes legacy states:

- `pending` -> `queued`
- `complete` -> `succeeded`
- `reboot_required` -> `succeeded` with reboot detail retained separately

The old telemetry service remains installed but disabled on a 0.5 student so rollback can restore the 0.4 path.
