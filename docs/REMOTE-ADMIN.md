# LGHS Remote Administration

LGCSCONT remains the single authoritative controller. Trusted administrator workstations connect to it through a dedicated constrained SSH identity and then invoke the same controller-local Fleet/recovery operations used by the console.

A remote workstation does **not** receive controller Fleet tokens, Cloudflare API credentials, `/etc/lghs/secrets/controller_ed25519`, the release-signing private key, or the controller database.

## Security model

- One Ed25519 SSH key per administrator workstation.
- Dedicated locked account: `lghs_remote`.
- Public-key authentication only.
- No SSH agent, X11, TCP, or tunnel forwarding.
- Every key is forced through `/usr/local/sbin/lghs-remote-shell`.
- The forced shell validates command names and arguments before dispatch.
- Sudoers separately allowlists the corresponding controller helpers.
- LGCSCONT remains the only revision/signing/provisioning authority.

The standard controller installer maintains the remote-admin runtime. `controller/install-remote-admin` remains available as an explicit repair/reinstall helper.

## Windows workstation setup

Clone LGHS-System, then run in PowerShell:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
& .\tools\windows-remote-admin\Install-LGHS-Remote.ps1
```

The helper verifies OpenSSH, installs `cloudflared` when needed, creates a workstation-specific Ed25519 key, adds the `LGHS-Control` SSH profile, and creates `%USERPROFILE%\bin\lghs.cmd`.

## Enroll or revoke a workstation

On LGCSCONT:

```bash
sudo lghs-remote-admin enroll main-pc
sudo lghs-remote-admin list
sudo lghs-remote-admin fingerprint
```

Paste the one-line workstation public key during `enroll`. Verify the controller SSH host-key fingerprint on first connection before accepting it.

To revoke only that workstation:

```bash
sudo lghs-remote-admin revoke main-pc
```

No Student Pi re-enrollment, Fleet-token rotation, or release-key rotation is required when one administrator workstation is revoked.

## Normal remote use

With no arguments, `lghs` opens Fleet Control remotely. Useful read-only checks include:

```powershell
lghs status
lghs info CS-999
lghs health CS-999
lghs check CS-999
lghs controller-runtime
lghs release-status
lghs command-status CS-999
lghs classroom-ready CS-999
```

Managed operations stay typed:

```powershell
lghs update CS-999
lghs update-exact CS-999 <40-character-sha> main
lghs os-update CS-999
lghs restart-service CS-999 agent
lghs reboot CS-999
lghs release-install-key CS-999
lghs backup-controller
lghs verify-migration CS-999
lghs command-cancel <command-id>
```

`lghs update DEVICE` does **not** make the student follow branch HEAD. It resolves to LGCSCONT's currently installed exact SHA. `update-exact` is the explicit deployment primitive and signed-release metadata is attached by the controller when signing is active.

`release-install-key` distributes only the Ed25519 public verification key. `release-keygen` is a one-time controller operation; the private key remains under `/etc/lghs/secrets` on LGCSCONT.

`verify-migration DEVICE` is not a generic readiness bypass. It only records provenance for an already-managed legacy device after every non-bootstrap `CLASSROOM READY` gate is already passing.

## Explicit recovery paths

```powershell
lghs logs CS-999 update
lghs ssh CS-999
lghs enforce CS-999
lghs sudo-list CS-999
lghs sudo-approve CS-999 <request-id>
lghs sudo-deny CS-999 <request-id>
```

Cloudflare SSH is used for explicit administrator/recovery work. Passive liveness and normal command delivery remain HTTPS Fleet responsibilities.

## Why remote workstations are not controllers

LGHS intentionally avoids copying controller credentials and command databases to administrator PCs. Multiple independent controllers could race command state, release sequence, deployment ownership, or acknowledgement history.

Remote workstations are therefore authenticated front ends to LGCSCONT. Controller redundancy, if added later, must replicate authoritative state with explicit leader/failover semantics rather than by copying credentials to multiple independent machines.
