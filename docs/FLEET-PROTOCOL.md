# LGHS Fleet Protocol v1

LGHS 0.5 formalizes the controller/student contract. Normal fleet operations use outbound HTTPS. Cloudflare SSH remains an explicit administration and recovery path, not the passive data plane.

## Telemetry envelope

Every 0.5 agent report will carry an envelope like:

```json
{
  "protocol": 1,
  "agent_version": "0.5.0",
  "device_id": "CS-999",
  "boot_id": "...",
  "sequence": 48291,
  "sent_at": 1788068837.1,
  "payload": {
    "health": {},
    "metrics": {},
    "command_states": []
  }
}
```

`boot_id + sequence` gives the controller an ordering key that survives reconnects and clearly resets after reboot.

## Controller response

```json
{
  "protocol": 1,
  "received_at": 1788068837.2,
  "commands": []
}
```

The initial transport remains the existing telemetry request/response exchange. Long polling will be added after the persistent agent is in place.

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

The controller may redeliver until `ACCEPTED`. Device-side acceptance/execution must therefore be idempotent.

Examples of `stage` values are `Fetching GitHub`, `Installing`, `Validating`, `Rolling back`, and `Reboot required`. These are descriptive details, not protocol states.

## Compatibility

During the staged 0.4 -> 0.5 migration the controller normalizes legacy states:

- `pending` -> `queued`
- `complete` -> `succeeded`
- `reboot_required` -> `succeeded` with reboot detail retained separately

Old telemetry remains supported until the 0.5 agent has been proven on real devices.

## Controller state

The target source of truth is `/var/lib/lghs/fleet.db`, SQLite in WAL mode. The schema includes devices, latest telemetry, commands, command events, warnings, deployments, sudo requests, audit events, notifications, and settings.

Legacy JSON files remain compatibility/export surfaces during migration; new code must not create an additional independent command writer.

## Security boundary target

0.5 moves toward two student processes:

```text
lghs-agent (unprivileged)
  telemetry / events / command transport
          |
          | typed local IPC
          v
lghs-command-executor (root)
  strict allowlist only
```

The root executor must never accept arbitrary shell text from the network.
