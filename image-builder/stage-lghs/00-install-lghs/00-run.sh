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

# Ensure no deployment secret accidentally survives image creation.
rm -f "${ROOTFS_DIR}/etc/lghs/secrets/controller_ed25519" \
      "${ROOTFS_DIR}/etc/lghs/secrets/controller_ed25519.pub" \
      "${ROOTFS_DIR}/etc/lghs/controller_ed25519.pub"

rm -rf "${ROOTFS_DIR}${CHROOT_SOURCE}"
echo "LGHS: ${LGHS_ROLE} role installed for ${IMAGE_HOSTNAME}."
echo "LGHS: first-boot Imager provisioning enabled."
echo "LGHS: fleet key material will be injected by LGHS Imager per deployment."
