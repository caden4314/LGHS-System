# LGHS Raspberry Pi hostname migration

## Goal

Give each Raspberry Pi a descriptive **static hostname** while preserving its original, authenticated `CS-XX` **device identity**, account, and Cloudflare endpoint.

**Do not rename production Pis until the accompanying identity-decoupling changes have been deployed and verified.**

| Permanent Fleet ID | Static Linux hostname | Pretty/display hostname | Existing desktop user |
| --- | --- | --- | --- |
| CS-01 | cs3-hr2-01 | CS3_HR2_01 | cs-01 |
| CS-02 | cs4-hr2-02 | CS4_HR2_02 | cs-02 |
| CS-03 | cs2-hr2-03 | CS2_HR2_03 | cs-03 |
| CS-04 | cs1-hr2-04 | CS1_HR2_04 | cs-04 |
| CS-05 | cs3-hr3-05 | CS3_HR3_05 | cs-05 |
| CS-06 | cs4-hr3-06 | CS4_HR3_06 | cs-06 |
| CS-07 | cs2-hr3-07 | CS2_HR3_07 | cs-07 |
| CS-08 | cs1-hr3-08 | CS1_HR3_08 | cs-08 |
| CS-09 | cs1-hr4-09 | CS1_HR4_09 | cs-09 |
| CS-10 | cs2-hr4-10 | CS2_HR4_10 | cs-10 |
| CS-11 | cs3-hr4-11 | CS3_HR4_11 | cs-11 |
| CS-12 | cs4-hr4-12 | CS4_HR4_12 | cs-12 |

### Why the names differ

Underscores are suitable in the pretty hostname, but not in DNS-compliant Linux static hostnames. Use `cs3-hr2-01` for network hostname and `CS3_HR2_01` for human-readable hostname.

### Deployment order

1. Deploy the compatible LGHS code first. The agent, legacy telemetry, command executor, lifecycle notifier, shell report, bootstrap, and Bluetooth enrollment verification must resolve identity from `/etc/lghs/device.conf` (`DEVICE_ID=CS-XX`), not from `socket.gethostname()`.
2. Verify live Fleet telemetry, update commands, monitoring, and SSH for each original `CS-XX` before changing names.
3. For each Pi, back up `/etc/hostname`, `/etc/hosts`, and `/etc/machine-info`. Confirm that `/etc/lghs/device.conf` contains the expected permanent Fleet ID and that the student account is still `cs-XX`.
4. Set the static and transient hostname with `hostnamectl hostname --static <new-hostname>` (or `hostnamectl set-hostname --static` on older versions); set the pretty hostname separately using `hostnamectl hostname --pretty <display-name>`. Update only the matching old host entry in `/etc/hosts`, preserving a legacy alias if present.
5. Validate `hostname`, `hostnamectl`, `lghs-report summary` (`hostname=CS-XX`, `system_hostname=<new-hostname>`), `lghs-agent.service`, Fleet report freshness, Cloudflare SSH endpoint, Raspberry Pi Connect as `cs-XX`, and automatic startup. Roll back immediately if Fleet authentication fails.
6. Proceed to the next device only after the current one passes.

### Identity and network endpoints that must not change

- `DEVICE_ID=CS-XX` in `/etc/lghs/device.conf`
- Registry keys `CS-XX`, associated Fleet API authorization and enrollment tokens
- `cs-XX` desktop user and `cs-admin` remote administration user
- Cloudflare SSH hosts `ssh-cs-XX.scenicrouteservers.com` and their established SSH host keys
- Any per-device key material, state, or registration

### Rollback

If a renamed device fails checks, restore its backed-up `/etc/hostname`, `/etc/hosts`, and `/etc/machine-info`, then restore the previous static/transient hostnames using `hostnamectl`. Do **not** regenerate device credentials or re-enroll the Pi. Validate with `sudo lghsctl info CS-XX` on the Fleet Controller after connectivity returns.

### Compatibility caveat

The Raspberry Pi Connect local setup helper on LGCSCONT also validates desktop users against hostnames and must accept the new naming pattern before renaming.
