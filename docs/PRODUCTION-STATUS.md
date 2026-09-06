# LGHS 0.6.0 Production Status

Status date: **2026-09-06**

LGHS 0.6.0 is the current classroom production release. The release is sourced from protected `main`; student software changes are deployed only as controller-authorized exact Git SHAs with Ed25519 release manifests after key enrollment.

## Managed production fleet

| Device | Role | Production state |
| --- | --- | --- |
| `LGCSCONT` | Controller | Authoritative Fleet/release/provisioning controller |
| `CS-01` | Student | `CLASSROOM READY` |
| `CS-02` | Student | `CLASSROOM READY` |
| `CS-03` | Student | `CLASSROOM READY` |
| `CS-999` | Student/canary | `CLASSROOM READY` |

`CS-04` through `CS-14` are future provisioning targets. They are not considered enrolled or healthy until they complete the stock zero-touch transaction and pass `lghs-classroom-ready`.

## Release and GitHub controls

- Production version: `0.6.0`.
- Release tag: `v0.6.0`.
- Default branch: `main`.
- `main` requires pull requests and required CI checks.
- Force-push and branch deletion on `main` are blocked.
- Feature branches are deleted after merge; stale historical branches are not retained.
- Student timers cannot select a new revision by following branch HEAD.
- LGCSCONT is the exact-SHA release authority.

## Live acceptance completed

The managed fleet has completed the non-destructive production acceptance work used for the 0.6.0 rollout:

- Exact-SHA controller/student convergence.
- Signed release public-key enrollment and signed-update enforcement.
- Structured health with critical/advisory severity handling.
- `CLASSROOM READY` acceptance on all four managed students.
- Planned reboot lifecycle proof without a false `OFFLINE` transition.
- Durable lifecycle history and reboot return/downtime tracking.
- Agent/executor/policy typed restart recovery.
- Durable network queue and command idempotency behavior.
- Controller SQLite WAL mode with `synchronous=FULL`.
- Live online controller backup with `PRAGMA quick_check = ok`.
- Backup retention: 7 daily, 4 weekly, 3 monthly.
- Restricted remote administration through `lghs_remote` forced commands.

The live reboot acceptance sequence on the canary converged through `SHUTDOWN` and startup `CHECK` states back to `OK` without a false runtime `OFFLINE` state.

## Zero-touch enrollment completion boundary

A new production student is ready only after this order succeeds:

```text
Bluetooth authentication
-> Cloudflare SSH verified
-> Fleet credential installed
-> first authenticated Fleet telemetry
-> release verification public key confirmed
-> bootstrap credential consumed
-> CLASSROOM READY
```

The controller release-signing private key never leaves LGCSCONT. Fresh students receive only the public verification key, and production bootstrap retains its one-time credential if signing confirmation does not arrive.

## Operator verification

From an authorized Windows workstation:

```powershell
lghs status
lghs controller-runtime
lghs release-status
lghs health CS-999
lghs check CS-999
lghs classroom-ready CS-999
lghs backup-controller
```

For a managed exact-SHA update:

```powershell
lghs update-exact CS-999 <40-character-sha> main
```

Use `lghs command-status DEVICE` for typed command diagnostics. `verify-migration DEVICE` is only for an already-managed legacy device whose runtime is fully healthy but whose historical registry lacks modern bootstrap provenance.

## Intentionally deferred

- Sudden power-loss testing during software update on classroom hardware.
- Full A/B operating-system update frameworks such as Mender/OSTree.
- A browser Fleet Web UI.
- Credential rotation solely for release promotion.

The software updater is validated and rollback-capable, but it is **not guaranteed atomic across sudden power loss during an update**. Destructive testing belongs on sacrificial recoverable hardware.
