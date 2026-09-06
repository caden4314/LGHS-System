# LGHS System

[![Validate LGHS](https://github.com/caden4314/LGHS-System/actions/workflows/validate.yml/badge.svg?branch=main)](https://github.com/caden4314/LGHS-System/actions/workflows/validate.yml)
[![LGHS Validate](https://github.com/caden4314/LGHS-System/actions/workflows/lghs-validate.yml/badge.svg?branch=main)](https://github.com/caden4314/LGHS-System/actions/workflows/lghs-validate.yml)
[![Rollout Validate](https://github.com/caden4314/LGHS-System/actions/workflows/lghs-06-rollout.yml/badge.svg?branch=main)](https://github.com/caden4314/LGHS-System/actions/workflows/lghs-06-rollout.yml)
[![Zero Touch Validate](https://github.com/caden4314/LGHS-System/actions/workflows/zero-touch-image-validate.yml/badge.svg?branch=main)](https://github.com/caden4314/LGHS-System/actions/workflows/zero-touch-image-validate.yml)

LGHS is a classroom management system for one Raspberry Pi controller (`LGCSCONT`) and managed Raspberry Pi 5 student devices (`CS-01`, `CS-02`, and so on).

The production deployment model is **stock Raspberry Pi OS plus zero-touch LGHS provisioning**. Custom `pi-gen` images remain optional/legacy tooling; they are not the primary fleet architecture.

For the full trust model and data/control flows, see [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

## Current production status

The current production release is **LGHS 0.6.0**. `main` is protected and changes flow through pull requests plus four required validation checks. The managed production fleet is LGCSCONT plus CS-01, CS-02, CS-03, and CS-999; the enrolled students have passed the controller-side `CLASSROOM READY` gate with signed exact-SHA updates enabled. CS-04 through CS-14 remain future provisioning targets and are not assumed enrolled.

See [`docs/PRODUCTION-STATUS.md`](docs/PRODUCTION-STATUS.md) for the live acceptance summary and supported operational checks.

## Production invariants

- Bluetooth is bootstrap-only and is treated as an untrusted transport.
- Cloudflare outbound tunnels are the remote SSH path; the school LAN is not assumed to permit client-to-client management.
- The HTTPS Fleet API is the normal runtime command and telemetry plane.
- Student software updates are selected by LGCSCONT as an **exact Git SHA**; students do not autonomously follow branch HEAD.
- Once the release public key is enrolled, exact-SHA student updates also require an Ed25519-signed release manifest.
- The Fleet agent is unprivileged. Root operations go through small typed local executors.
- Student sudo is brokered through Fleet approval with a local-root recovery path.
- Controller state is SQLite in WAL mode with `synchronous=FULL` and verified online backups.
- Planned shutdown/reboot lifecycle state overrides ordinary telemetry-loss alarms.
- Existing SSH, Fleet, Cloudflare, and Bluetooth identities are separate trust roles from the release-signing key.

## Provisioning

The stock-device transaction is:

```text
stock Raspberry Pi OS
  -> password-derived per-device Bluetooth bootstrap credential
  -> X25519 + HKDF + AES-GCM + HMAC provisioning session
  -> Wi-Fi and Cloudflare tunnel installation
  -> LGCSCONT verifies the student's Cloudflare SSH endpoint
  -> LGCSCONT mints the Fleet credential
  -> student installs/starts Fleet runtime
  -> LGCSCONT observes the first authenticated Fleet report
  -> LGCSCONT enrolls the Ed25519 release verification public key
  -> fresh Fleet health confirms release signing
  -> bootstrap credential is consumed
  -> CLASSROOM READY acceptance gate
```

A device is not considered ready merely because Bluetooth or Cloudflare setup completed. `lghs-classroom-ready DEVICE` requires fresh authenticated telemetry, expected identity, Cloudflare registration, core services, policy, sudo broker, lifecycle service, a valid enrolled release verification key, zero failed systemd units, the expected exact commit, and the `main` update channel.

See [`bootstrap/STOCK-SETUP.md`](bootstrap/STOCK-SETUP.md) and [`docs/BLUETOOTH-BOOTSTRAP.md`](docs/BLUETOOTH-BOOTSTRAP.md) for provisioning procedures.

## Updates and releases

The production software path is:

```text
feature branch -> pull request -> required CI -> protected main
  -> LGCSCONT selects exact SHA
  -> signed release manifest (after key enrollment)
  -> HTTPS Fleet command
  -> durable student queue
  -> signature/sequence/expiry verification
  -> install + structured validation
  -> success or rollback
```

Student `lghs-update.timer` remains enabled for reconciliation/timer compatibility, but an unpinned student run cannot select a new Git revision. Channel-only commands may persist metadata without resolving branch HEAD.

The release-signing private key lives only on LGCSCONT at `/etc/lghs/secrets/release-signing-key`. Students receive only `/etc/lghs/release-public-key`. Key replacement is intentionally not a normal Fleet operation.

Emergency local-root recovery can explicitly permit an unsigned release or a sequence rollback. Those overrides are not exposed by the Fleet executor.

**Power-loss limitation:** LGHS software updates are validated and rollback-capable, but are not guaranteed atomic across sudden power loss during an update.

## Runtime operations

LGCSCONT keeps the authoritative device registry, Fleet command state, telemetry, lifecycle history, sudo state, rollout state, and warnings. The Fleet API and controller services read/write the SQLite database transactionally.

Telemetry normally arrives every few seconds. Operator state uses a grace model rather than immediately declaring a device offline: fresh reports are normal, then `STALE`, then `OFFLINE`. A reported planned poweroff shows `SHUTDOWN`; a planned reboot shows `REBOOTING` until a new boot ID returns.

Controller backups use SQLite's online backup API, `PRAGMA quick_check`, fsync, and atomic promotion. Retention is 7 daily, 4 weekly, and 3 monthly snapshots. The backup allowlist includes non-secret controller configuration and release sequence state, but never copies `/etc/lghs/secrets` or Fleet token stores.

Remote administration uses the dedicated `lghs_remote` account with a forced allowlisted shell. See [`docs/REMOTE-ADMIN.md`](docs/REMOTE-ADMIN.md).

## Repository layout

- `controller/` — Fleet API, CLI/console, provisioning, release management, lifecycle, rollouts, backups, and acceptance.
- `student/` — agent, typed executor, policy enforcement, sudo broker, health checks, lifecycle reporting, and bootstrap client.
- `bluetooth/` — authenticated/encrypted Bluetooth protocol and preparation helpers.
- `updater/` — exact-SHA software updates, OS updates, durable network queue, and reconciliation.
- `policies/` — sudoers and PolicyKit policy templates.
- `systemd/` — controller/student services and timers.
- `bootstrap/` — stock Raspberry Pi OS bootstrap path.
- `image-builder/` — optional/legacy custom-image integration.
- `docs/` — architecture, protocol, bootstrap, remote-administration, and hardware-validation documentation.
