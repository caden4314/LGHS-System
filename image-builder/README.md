# LGHS Raspberry Pi Image Builder

The image builder produces one generic Raspberry Pi OS 64-bit Desktop image for Raspberry Pi 5 student systems.

The image should contain only generic LGHS software and policy. Do **not** bake class passwords, school Wi-Fi credentials, GitHub tokens, roster data, or SSH private keys into the image.

## Planned flow

1. Build from Raspberry Pi OS 64-bit Desktop with `pi-gen`.
2. Install `lghs-agent`, `lghs-enforce`, `lghs-check`, systemd units, Avahi, SSH, NetworkManager, PolicyKit, Python, Git and classroom development tools.
3. First boot advertises `_lghs._tcp` on the local network.
4. The control Pi discovers the new system and assigns its device ID/group.
5. The control Pi provisions group credentials and approved Wi-Fi configuration over the management channel.

The standalone `LGHS_RPi5_Image_Builder_v0.1.0` package is the current development builder. Its contents will be migrated here once the first physical Pi build is validated.
