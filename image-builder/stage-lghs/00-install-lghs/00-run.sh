#!/bin/bash -e

HOSTNAME_FILE="${ROOTFS_DIR}/etc/hostname"
[[ -f "$HOSTNAME_FILE" ]] || { echo "LGHS: missing $HOSTNAME_FILE" >&2; exit 1; }
IMAGE_HOSTNAME="$(tr -d '[:space:]' < "$HOSTNAME_FILE")"
IMAGE_HOSTNAME_LOWER="$(printf '%s' "$IMAGE_HOSTNAME" | tr '[:upper:]' '[:lower:]')"
[[ -n "$IMAGE_HOSTNAME" ]] || { echo "LGHS: image hostname is empty" >&2; exit 1; }
case "$IMAGE_HOSTNAME_LOWER" in *cont*) LGHS_ROLE="controller" ;; *) LGHS_ROLE="student" ;; esac

echo "LGHS: detected image hostname: ${IMAGE_HOSTNAME}"
echo "LGHS: selected role: ${LGHS_ROLE}"
echo "LGHS: stock Raspberry Pi OS arm64 base via RPi-Distro/pi-gen"
echo "LGHS: deployment fleet keys are NOT baked into the image"

SOURCE_DIR="${STAGE_DIR}/00-install-lghs/files/LGHS-System"
[[ -f "$SOURCE_DIR/install.sh" ]] || { echo "LGHS: staged source missing" >&2; exit 1; }

CHROOT_SOURCE="/opt/lghs-build-source"
rm -rf "${ROOTFS_DIR}${CHROOT_SOURCE}"
mkdir -p "${ROOTFS_DIR}${CHROOT_SOURCE}"
cp -a "$SOURCE_DIR/." "${ROOTFS_DIR}${CHROOT_SOURCE}/"
chmod 0755 "${ROOTFS_DIR}${CHROOT_SOURCE}/install.sh"

install -d -m 0755 "${ROOTFS_DIR}/etc/lghs"
install -d -m 0700 "${ROOTFS_DIR}/etc/lghs/secrets"
printf '%s\n' "$IMAGE_HOSTNAME" > "${ROOTFS_DIR}/etc/lghs/build-hostname"
printf '%s\n' "$LGHS_ROLE" > "${ROOTFS_DIR}/etc/lghs/build-role"

on_chroot <<EOF
set -e
cd ${CHROOT_SOURCE}
LGHS_IMAGE_BUILD=1 /bin/bash ./install.sh ${LGHS_ROLE}
if [[ "${LGHS_ROLE}" == "student" ]]; then
    python3 ./updater/patch-agent-root-writable.py /usr/local/sbin/lghs-agent
    chown root:root /usr/local/sbin/lghs-agent
    chmod 0755 /usr/local/sbin/lghs-agent
    /bin/bash ./student/lghs-install-network-ui
fi
EOF

# Keep the classroom development environment available in both roles.
on_chroot <<'EOF'
apt-get update
DEBIAN_FRONTEND=noninteractive apt-get install -y \
    code python3 python3-pip python3-venv python3-dev pipx git build-essential
/usr/local/sbin/lghs-dev-setup || true
EOF

# LGHS owns first-boot identity, passwords, networking, and the desktop login.
# Remove Raspberry Pi OS's first-user wizard path even during --fast builds
# that reuse an older stage4 cache.
on_chroot <<'EOF'
set -e

rm -f /etc/xdg/autostart/piwiz.desktop
rm -f /etc/ssh/sshd_config.d/rename_user.conf
rm -f /etc/sudoers.d/010_wiz-nopasswd
rm -f /var/lib/userconf-pi/autologin

systemctl disable userconfig.service >/dev/null 2>&1 || true
systemctl mask userconfig.service >/dev/null 2>&1 || true
rm -f /etc/systemd/system/multi-user.target.wants/userconfig.service

# Cloud-init is useful for generic Pi images but LGHS has its own deterministic
# first-boot provisioner. Disable it here too so a cached rootfs cannot revive
# an independent first-boot workflow.
install -d -m 0755 /etc/cloud
touch /etc/cloud/cloud-init.disabled
systemctl disable cloud-init-local.service cloud-init-network.service \
    cloud-config.service cloud-final.service cloud-init.target >/dev/null 2>&1 || true

# Never allow a legacy console-autologin override to win at tty1. LGHS should
# proceed from its firstboot provisioner directly into the graphical desktop.
rm -f /etc/systemd/system/getty@tty1.service.d/autologin.conf
rmdir --ignore-fail-on-non-empty /etc/systemd/system/getty@tty1.service.d 2>/dev/null || true
systemctl set-default graphical.target
systemctl enable lightdm.service >/dev/null 2>&1 || true

# Re-apply the canonical LGHS desktop policy after stripping the distro wizard.
/usr/local/sbin/lghs-autologin-apply

echo "LGHS: Raspberry Pi first-run wizard disabled."
echo "LGHS: default boot target: $(systemctl get-default)"
EOF

# Ensure no deployment secret accidentally survives image creation.
rm -f "${ROOTFS_DIR}/etc/lghs/secrets/controller_ed25519" \
      "${ROOTFS_DIR}/etc/lghs/secrets/controller_ed25519.pub" \
      "${ROOTFS_DIR}/etc/lghs/controller_ed25519.pub"

rm -rf "${ROOTFS_DIR}${CHROOT_SOURCE}"
echo "LGHS: ${LGHS_ROLE} role installed for ${IMAGE_HOSTNAME}."
echo "LGHS: first-boot Imager provisioning enabled."
echo "LGHS: Raspberry Pi interactive first-run disabled."
echo "LGHS: graphical desktop boot enforced."
echo "LGHS: fleet key material will be injected by LGHS Imager per deployment."
