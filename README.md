# LGHS System

LGHS is a classroom Raspberry Pi management system for one Control Pi and a fleet of Student Raspberry Pi 5 systems.

## Current deployment baseline

The current runtime release is **V0207**. The active Windows LGHS Imager supports Raspberry Pi 5 **4 GB and 8 GB** hardware profiles using the same Raspberry Pi OS arm64 base.

## Goals

- One generic managed Student software stack for the fleet.
- Automatic local-network discovery with encrypted SSH management.
- Central management from the LGHS Control Pi.
- Restricted student sudo with exact-command Fleet approval and Root-password local fallback.
- Protected NetworkManager profiles and student network UI restrictions.
- Versioned policy/software updates with validation, persistent offline retry, and rollback hooks.
- Responsive Fleet console with Needs Attention, activity history, desktop notifications, and live aggregate network rates.
- No student passwords, Wi-Fi passwords, private keys, or tokens committed to Git.

## Layout

- `controller/` — Control-Pi CLI, Fleet console, notifications, and audit collection.
- `student/` — Student-Pi agent, policy enforcement, sudo broker, health checks, and dev setup.
- `policies/` — sudoers and PolicyKit policy templates.
- `systemd/` — boot/update/reconcile/notification services and timers.
- `updater/` — live update, OS update, self-heal, autologin, and offline network queue helpers.
- `image-builder/` — optional Raspberry Pi OS/pi-gen custom-image integration.

## Runtime model

A stock-bootstrap deployment stages role/account/network information on the boot partition, uses cloud-init to establish early SSH recovery, then hands local provisioning to `lghs-stage2-bootstrap.service`. Stage 2 installs the deployment Fleet identity and launches the online LGHS-System bootstrap. The full install writes `/var/lib/lghs/bootstrap-complete`; the one-time desktop notifier only reports success after that marker exists.

Live LGHS updates pull the configured branch over HTTPS/Git, reinstall managed files, validate the resulting Student or Control role, and roll back to the previous commit when validation fails. Reconcile periodically reapplies managed configuration after package or OS changes.

## Fleet network security

- Control-to-Student management and audit collection use SSH with the deployment Ed25519 key.
- Fleet SSH clients require the pinned `known_hosts` entry after first enrollment and disable password fallback, agent forwarding, X11 forwarding, and tunnel/port forwarding.
- Student `cs_admin` Fleet SSH is public-key-only.
- Avahi/mDNS is used only for local discovery metadata and is not an encrypted transport.
- Direct Ethernet itself is not link-layer encrypted; LGHS management crossing that link is still carried inside SSH.
- NetworkManager connection profiles are root-owned mode `0600` and the student account is blocked from advanced connection editing/secret management.

First-contact Student SSH host-key enrollment currently uses an Ed25519 `ssh-keyscan`/TOFU model. Pre-pinned host identities or an SSH host CA are future hardening options for environments where hostile local-network MITM is in scope.

## Security

Never commit:

- classroom/student passwords
- school Wi-Fi credentials
- SSH private keys
- GitHub tokens
- roster spreadsheets containing credentials

Keep deployment secrets under `/etc/lghs/secrets/` on the Control Pi with root-only permissions. Provisioning secrets placed temporarily on the FAT boot partition are deployment material, not encrypted at rest; they are removed after successful first-boot provisioning.
