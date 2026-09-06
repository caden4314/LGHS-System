# LGHS Architecture

This document describes the production LGHS classroom architecture. The primary deployment is stock Raspberry Pi OS with automated LGHS provisioning; custom images are optional/legacy.

## 1. System roles

### LGCSCONT

The controller is the authority for enrollment, Fleet commands, exact-SHA software selection, release signing, rollouts, sudo approval, lifecycle history, acceptance, and controller backups.

Important controller state includes:

- `/etc/lghs/fleet.json` — enrolled transport registry.
- `/var/lib/lghs/fleet.db` — authoritative SQLite Fleet state.
- `/var/lib/lghs/fleet-cache.json` — compatibility/UI cache derived from authenticated reports.
- `/var/lib/lghs/release/` — non-secret signed-release sequence/current manifest state.
- `/etc/lghs/secrets/` — root-only controller secrets; never part of normal backups.

### Student Pis

Students run an unprivileged Fleet agent and a narrow root-owned command executor. Students report telemetry/health to LGCSCONT and receive typed work over the HTTPS Fleet API. They do not choose their own software revision.

## 2. Trust boundaries and identities

LGHS deliberately separates credentials by role:

- **Bluetooth bootstrap credential:** short-lived, per-device credential used only for initial mutual application authentication.
- **Controller Fleet SSH key:** Ed25519 key used by LGCSCONT for enrolled administrative SSH operations.
- **Fleet API device token:** per-device bearer credential used by the student to authenticate HTTPS reports/command polling.
- **Fleet API admin token:** controller-local administration credential for the Fleet API.
- **Cloudflare API/tunnel credentials:** used to create and operate outbound Cloudflare tunnels.
- **Remote admin key:** workstation-specific key for the forced `lghs_remote` controller shell.
- **Release-signing key:** separate Ed25519 private key used only to sign software release manifests.

Compromise of one role should not automatically grant every other role. The release-signing private key is not reused for SSH, Bluetooth, Fleet API authentication, or Cloudflare.

Student root operations are not exposed as a generic remote shell. Fleet commands are parsed by the unprivileged agent and passed through a local Unix socket to the root-owned typed executor. Only explicitly supported actions and payload fields are accepted.

The `lghs_remote` controller account is similarly constrained by an SSH `ForceCommand` allowlist. It cannot turn the remote-management path into an unrestricted controller shell.

## 3. Zero-touch provisioning transaction

Provisioning is intentionally ordered so later credentials are not created before earlier trust checks pass:

```text
BT_AUTH
  -> WIFI_INSTALLED
  -> CF_ALLOCATED
  -> CF_VERIFIED
  -> FLEET_ENROLLED
  -> FIRST_TELEMETRY
  -> ACCEPTANCE
  -> READY
```

1. A stock student has a short-lived per-device bootstrap credential derived from the configured stock provisioning secret.
2. Student and controller authenticate the Bluetooth transcript using HMAC proofs and ephemeral X25519 keys.
3. HKDF derives the session key; Wi-Fi/Cloudflare data is carried only inside AES-GCM ciphertext.
4. The student installs Wi-Fi and an outbound Cloudflare tunnel and returns its Ed25519 SSH host key.
5. LGCSCONT finalizes/pins the Cloudflare SSH identity and verifies SSH through Cloudflare.
6. Only after that verification does LGCSCONT mint a per-device Fleet token.
7. The student installs its Fleet identity, starts the agent/executor/policy services, and reports `fleet-ready`.
8. LGCSCONT waits until the Fleet database contains a new authenticated report from the expected device identity.
9. Only then is the one-time Bluetooth bootstrap credential consumed.
10. `lghs-classroom-ready DEVICE` evaluates the full runtime before the device is considered classroom ready.

## 4. Cloudflare and runtime transport

School guest networks may isolate clients, so LGHS does not depend on direct student-to-controller LAN reachability for normal management.

Each enrolled student establishes an outbound `cloudflared` tunnel. LGCSCONT keeps the expected Cloudflare SSH hostname and pinned host key in its registry. Cloudflare SSH is used for explicit administrative/recovery actions; passive fleet health and normal command delivery use HTTPS.

The controller also exposes the Fleet API through its Cloudflare path. Student agents authenticate every report and command poll with a device-specific token. The API persists authenticated telemetry before compatibility caches are refreshed, so SQLite is the authoritative evidence for first-report provisioning and classroom acceptance.

Avahi/mDNS is only a provisioning/recovery discovery signal. It is not treated as an authenticated control plane.

## 5. Fleet command delivery

The normal command path is:

```text
LGCSCONT -> SQLite command row -> HTTPS long poll -> unprivileged agent
  -> root-owned typed executor -> durable local queue / typed helper
  -> command milestones -> authenticated Fleet report -> SQLite
```

Command IDs are also local idempotency keys. Received work is redelivered until locally accepted, while uncertain local executions are held for explicit recovery rather than blindly repeated.

## 6. Student sudo approval

The classroom student account does not receive unrestricted persistent root access. The LGHS `sudo` wrapper creates a request containing the exact command context. LGCSCONT receives the request through authenticated Fleet state and an administrator may approve or deny it.

Approved execution is performed by a root-owned typed helper and is audited. A local root/password recovery path remains available for maintenance when the controller path is unavailable.

The acceptance health report includes a `sudo.broker` check so a Pi cannot become `CLASSROOM READY` if the required sudo broker/approved-execution runtime is missing.

## 7. Software updates and signed releases

LGCSCONT is the revision authority. A student timer or reconciliation run cannot resolve `main` to a new software revision on its own.

After the release public key is enrolled, every managed student exact-SHA update requires a canonical Ed25519-signed manifest containing schema, release sequence, channel, version, exact commit, creation/expiration times, and minimum updater version.

Students verify the signature, exact commit, channel, expiry, minimum updater, and monotonically non-decreasing release sequence **before Git fetch/install work**. The accepted sequence is persisted only after the target revision validates successfully.

The controller signing key is `/etc/lghs/secrets/release-signing-key`; students store only `/etc/lghs/release-public-key`. The private key is explicitly excluded from normal controller backups.

Local-root emergency recovery may explicitly allow an unsigned release or release-sequence rollback. Those flags are not exposed by the Fleet command executor.

LGHS software updates are validated and rollback-capable, but are not guaranteed atomic across sudden power loss during an update.

## 8. Lifecycle and reboot semantics

Students report planned shutdown events with the current boot ID before normal network teardown. LGCSCONT persists those events in `device_lifecycle` and suppresses ordinary critical telemetry-loss alarms while the planned lifecycle state is authoritative.

Operator liveness is grace-based: fresh telemetry is normal, then `STALE`, then `OFFLINE`. A planned poweroff is shown as `SHUTDOWN`; a planned reboot is shown as `REBOOTING`.

Controller-scheduled reboots create an `expected_reboot` lifecycle record before dispatch. Completion is verified by observing a new boot ID. Lifecycle records capture return time and measured downtime.

## 9. SQLite durability and backups

The controller database uses:

```sql
PRAGMA journal_mode=WAL;
PRAGMA synchronous=FULL;
PRAGMA foreign_keys=ON;
PRAGMA busy_timeout=15000;
```

Backups use Python's SQLite online backup API, never a plain copy of a live WAL database. Each snapshot is checked with `PRAGMA quick_check`, fsynced, and atomically promoted. Retention is 7 daily, 4 weekly, and 3 monthly snapshots.

The safe sidecar allowlist may include non-secret registry/configuration and release sequence/current-manifest state. `/etc/lghs/secrets`, Fleet API token files, and the release-signing private key are not automatically copied.

## 10. Remote administration and recovery

Human remote access to LGCSCONT uses the dedicated `lghs_remote` account and an SSH forced command. The allowlist exposes status, health, exact-SHA updates, typed service recovery, release status/key enrollment, classroom acceptance, and sudo approval operations without granting a general-purpose remote controller shell.

Student recovery follows the same principle: Fleet Control may restart a small allowlist of services through `lghs-service-recovery`; it does not grant `cs_admin` unrestricted passwordless `systemctl`.

If normal Fleet delivery is unavailable, LGCSCONT can use its pinned Cloudflare SSH path for explicit recovery. Local root access remains the final emergency boundary for signing-key replacement, release rollback overrides, or other exceptional recovery.

## 11. CLASSROOM READY gate

A production-ready student must pass all of these controller-evaluated sections:

- Bootstrap evidence and enrolled registry state.
- Cloudflare transport registration.
- Fresh authenticated Fleet telemetry.
- Correct student identity/hostname.
- NetworkManager, SSH, agent, executor, and policy runtime.
- Sudo broker runtime.
- Lifecycle reporter runtime.
- Zero failed systemd units.
- Expected exact commit and `main` channel.

This gate is designed to be reused as CS-04 through CS-14 are provisioned; devices that are not yet enrolled are not assumed to exist or pass.

## 12. Optional/legacy image path

`image-builder/` and the related custom-image workflows remain useful for lab experiments, preloading packages, or environments that specifically want a prebuilt image. They are not the trust anchor for production LGHS enrollment.

The supported classroom architecture assumes a stock Raspberry Pi OS base followed by the authenticated provisioning and acceptance transaction above. This avoids coupling fleet identity and classroom secrets to a reusable image artifact.

## 13. Deliberately deferred changes

The current scale and constraints do not justify replacing the updater with a full A/B operating-system framework such as Mender, OSTree, or TUF-based OS deployment. LGHS also does not perform destructive sudden-power-loss acceptance tests on classroom hardware.

A browser Web UI is not part of the current production plan. Fleet Control, controller CLI, HTTPS API, and the restricted remote-admin shell are the supported operator surfaces.
