# LGHS System

LGHS is a classroom Raspberry Pi management system for a control Pi and a fleet of student Raspberry Pi 5 systems.

## Goals

- One generic student image for the fleet.
- Automatic discovery and enrollment on the classroom network.
- Central management from the LGHS control Pi.
- Restricted student sudo and protected NetworkManager secrets.
- Versioned policy/software updates with verification and rollback hooks.
- No student passwords, Wi-Fi passwords, private keys, or tokens committed to Git.

## Layout

- `controller/` — control-Pi CLI and fleet management.
- `student/` — student-Pi agent, policy enforcement, and health checks.
- `policies/` — sudoers and PolicyKit policy templates.
- `systemd/` — boot/update services and timers.
- `updater/` — update client/server helpers.
- `image-builder/` — Raspberry Pi OS image build integration.
- `docs/` — deployment and testing documentation.

## Current status

Version 0.1.0 is the initial development baseline. Test in Hyper-V before deploying to classroom Pis.

## Security

Never commit:

- class usernames/passwords
- school Wi-Fi credentials
- SSH private keys
- GitHub tokens
- roster spreadsheets containing credentials

Keep deployment secrets under `/etc/lghs/secrets/` on the control Pi with root-only permissions.
