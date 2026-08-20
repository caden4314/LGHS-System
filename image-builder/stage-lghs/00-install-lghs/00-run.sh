#!/bin/bash -e

# LGHS pi-gen stage
# Selects the LGHS role from the hostname already configured by pi-gen.
# Any hostname containing "cont" (case-insensitive) becomes a controller;
# everything else becomes a student image.

HOSTNAME_FILE="${ROOTFS_DIR}/etc/hostname"

if [[ ! -f "${HOSTNAME_FILE}" ]]; then
    echo "LGHS: ${HOSTNAME_FILE} does not exist; refusing to guess the image role." >&2
    exit 1
fi

IMAGE_HOSTNAME="$(tr -d '[:space:]' < "${HOSTNAME_FILE}")"
IMAGE_HOSTNAME_LOWER="$(printf '%s' "${IMAGE_HOSTNAME}" | tr '[:upper:]' '[:lower:]')"

if [[ -z "${IMAGE_HOSTNAME}" ]]; then
    echo "LGHS: image hostname is empty; refusing to guess the image role." >&2
    exit 1
fi

case "${IMAGE_HOSTNAME_LOWER}" in
    *cont*)
        LGHS_ROLE="controller"
        ;;
    *)
        LGHS_ROLE="student"
        ;;
esac

echo "LGHS: detected image hostname: ${IMAGE_HOSTNAME}"
echo "LGHS: selected role: ${LGHS_ROLE}"

# The build wrapper refreshes this directory from the checked-out LGHS-System
# repository immediately before invoking pi-gen.
SOURCE_DIR="${STAGE_DIR}/00-install-lghs/files/LGHS-System"

if [[ ! -f "${SOURCE_DIR}/install.sh" ]]; then
    echo "LGHS: staged source tree is missing: ${SOURCE_DIR}" >&2
    echo "LGHS: run image-builder/build-image.sh instead of invoking pi-gen directly." >&2
    exit 1
fi

rm -rf "${ROOTFS_DIR}/tmp/LGHS-System"
mkdir -p "${ROOTFS_DIR}/tmp/LGHS-System"
cp -a "${SOURCE_DIR}/." "${ROOTFS_DIR}/tmp/LGHS-System/"
chmod 0755 "${ROOTFS_DIR}/tmp/LGHS-System/install.sh"

# Record the build-time decision for diagnostics inside the finished image.
install -d -m 0755 "${ROOTFS_DIR}/etc/lghs"
printf '%s\n' "${IMAGE_HOSTNAME}" > "${ROOTFS_DIR}/etc/lghs/build-hostname"
printf '%s\n' "${LGHS_ROLE}" > "${ROOTFS_DIR}/etc/lghs/build-role"

on_chroot <<EOF
cd /tmp/LGHS-System
/bin/bash ./install.sh ${LGHS_ROLE}
EOF

rm -rf "${ROOTFS_DIR}/tmp/LGHS-System"

echo "LGHS: ${LGHS_ROLE} role installed for ${IMAGE_HOSTNAME}."
