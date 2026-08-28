# LGHS Versioning

LGHS uses Semantic Versioning (`MAJOR.MINOR.PATCH`).

- **MAJOR**: incompatible fleet-management, policy, image, or provisioning changes.
- **MINOR**: backwards-compatible features such as new Fleet Control capabilities, telemetry fields, update mechanisms, or admin workflows.
- **PATCH**: backwards-compatible bug, reliability, security-hardening, and UX fixes.

The repository `VERSION` file contains only the release version, for example `0.4.0`.

Every installed host also reports a build identity derived from the release and Git commit:

`0.4.0+1a2b3c4d`

The update branch is reported separately as the **channel**. `main` is the normal production channel. Development/test branches may be pinned through `/etc/lghs/update.env` using `LGHS_UPDATE_BRANCH=<branch>`.

A fleet device is therefore identified by three independent values:

- `version`: human release version (`0.4.0`)
- `build`: exact release/build shorthand (`0.4.0+1a2b3c4d`)
- `commit`: full source commit for exact comparison and rollback
- `channel`: update source branch (`main`, a test branch, etc.)

The controller may warn when a Pi's exact commit differs from the controller even if both report the same release version. This is intentional and catches partially deployed patches.
