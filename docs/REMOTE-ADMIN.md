# LGHS Remote Administration

LGHS keeps the Control Pi/Laptop as the single source of truth for fleet state and fleet credentials, while allowing additional trusted computers to manage the same fleet remotely.

The additional computer does **not** receive `/etc/lghs/secrets/controller_ed25519`, Cloudflare API credentials, fleet telemetry tokens, or the controller database. Instead it receives its own Ed25519 administrator key and connects to the Control Pi through the existing Cloudflare SSH hostname. The Control Pi then performs fleet operations locally using the same HTTPS command plane and explicit Cloudflare SSH recovery plane it already uses.

## Security model

- One SSH key per administrator workstation.
- Separate locked Linux account: `lghs_remote`.
- Password login disabled.
- Public-key authentication required.
- No SSH agent, X11, TCP, or tunnel forwarding.
- Every key is forced through `/usr/local/sbin/lghs-remote-shell`.
- The forced shell exposes only LGHS management commands.
- The controller fleet private key never leaves LGCSCONT.
- Revoking one workstation does not affect other administrators or Student Pis.

## Install on LGCSCONT

After checking out the feature/release containing this support:

```bash
cd /opt/lghs/repo
sudo ./controller/install-remote-admin
```

The installer prints the controller's Ed25519 SSH host-key fingerprint. Keep it available for first connection verification.

## Prepare the Windows main PC

Clone/download LGHS-System, then in PowerShell run:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
& .\tools\windows-remote-admin\Install-LGHS-Remote.ps1
```

The script:

1. verifies Windows OpenSSH;
2. installs `cloudflared` with winget when available and missing;
3. creates a workstation-specific Ed25519 key;
4. adds an `LGHS-Control` SSH profile using Cloudflare Access SSH;
5. creates `%USERPROFILE%\bin\lghs.cmd`;
6. prints the public key that must be enrolled on LGCSCONT.

No controller/fleet private key is copied to Windows.

## Enroll the Windows workstation

On LGCSCONT:

```bash
sudo lghs-remote-admin enroll main-pc
```

Paste the one-line `ssh-ed25519 ...` public key printed by the Windows installer and press `Ctrl+D`.

Check enrolled workstations:

```bash
sudo lghs-remote-admin list
```

Display the controller host-key fingerprint at any time:

```bash
sudo lghs-remote-admin fingerprint
```

## First connection

Open a new PowerShell window on Windows and run:

```powershell
lghs
```

OpenSSH will display the controller host-key fingerprint on first connection. Compare it to the value from `sudo lghs-remote-admin fingerprint` before accepting it.

With no arguments, `lghs` opens the normal Fleet Control console remotely in Windows Terminal.

## Remote commands

```powershell
lghs
lghs status
lghs update CS-999
lghs os-update CS-999
lghs update-controller
lghs check CS-999
lghs enforce CS-999
lghs reboot CS-999
lghs logs CS-999
lghs logs CS-999 update
lghs ssh CS-999
```

`update` and `os-update` are submitted to the controller's HTTPS fleet command plane. `ssh`, `logs`, `check`, `enforce`, and `reboot` are explicit administrator/recovery actions and use the controller's existing Cloudflare SSH path to the target Pi.

## Revoke a workstation

If a PC is lost, replaced, or should no longer manage the fleet:

```bash
sudo lghs-remote-admin revoke main-pc
```

The key is immediately removed from `lghs_remote`'s generated `authorized_keys` file. No Student Pi re-enrollment or fleet-key rotation is required.

For a replacement workstation, run the Windows installer again with a different administrator name and enroll the new public key.

## Why this is not a second controller

LGHS intentionally keeps authoritative state on LGCSCONT. Two independent controllers with copied fleet credentials and separate command databases could race each other, lose acknowledgements, or issue conflicting deployments. Remote administrator machines therefore act as authenticated front ends to the authoritative controller rather than becoming independent fleet controllers.

A future controller-redundancy feature can replicate the controller database and use leader election/failover, but that is a different problem from safe multi-workstation administration.
