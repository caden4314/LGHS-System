# LGHS Raspberry Pi Image Builder

`image-builder/` is **optional/legacy tooling**. The supported production classroom path is stock Raspberry Pi OS followed by authenticated LGHS zero-touch provisioning and `CLASSROOM READY` acceptance.

A custom image may still be useful for lab experiments, package preloading, or environments that intentionally want a reusable base image. It is not a fleet identity source, release authority, or substitute for controller-side enrollment.

## Security requirements

A reusable image must contain only generic software and policy. Never bake any of the following into an image:

- classroom/provisioning passwords;
- school Wi-Fi credentials;
- Fleet API tokens;
- Cloudflare tunnel tokens;
- controller or student SSH private keys;
- release-signing private keys;
- roster/device-specific enrollment state.

Device identity, Cloudflare registration, Fleet credentials, and the Ed25519 release verification public key must still be established through the normal provisioning/control plane.

## Production relationship

If the builder is used, the resulting Pi must still complete the same production gates as a stock install:

```text
Cloudflare verified -> Fleet authenticated -> release signing enrolled -> CLASSROOM READY
```

The image builder is not pinned as the production update mechanism. Runtime software promotion remains protected PR/CI -> LGCSCONT exact SHA -> signed Fleet release.
