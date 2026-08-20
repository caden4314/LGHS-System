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

# Classroom development environment shared by both roles.
# VS Code is distributed through the Raspberry Pi OS APT repositories.
on_chroot <<'EOF'
apt-get update
DEBIAN_FRONTEND=noninteractive apt-get install -y \
    code \
    python3 \
    python3-pip \
    python3-venv \
    python3-dev \
    pipx \
    git \
    build-essential
EOF

# Default VS Code settings for current and future classroom users.
install -d -m 0755 "${ROOTFS_DIR}/etc/skel/.config/Code/User"
cat > "${ROOTFS_DIR}/etc/skel/.config/Code/User/settings.json" <<'EOF'
{
    "python.defaultInterpreterPath": "/usr/bin/python3",
    "python.terminal.activateEnvironment": true,
    "python.createEnvironment.trigger": "off",
    "terminal.integrated.defaultProfile.linux": "bash",
    "files.autoSave": "afterDelay",
    "files.autoSaveDelay": 1000,
    "editor.formatOnSave": false,
    "workbench.startupEditor": "welcomePage"
}
EOF

# Put a clear VS Code launcher on the desktop. This is also placed in /etc/skel
# so any users created later receive it automatically.
install -d -m 0755 "${ROOTFS_DIR}/etc/skel/Desktop"
cat > "${ROOTFS_DIR}/etc/skel/Desktop/visual-studio-code.desktop" <<'EOF'
[Desktop Entry]
Version=1.0
Type=Application
Name=Visual Studio Code
Comment=Write and run code
Exec=/usr/bin/code
Icon=visual-studio-code
Terminal=false
Categories=Development;IDE;
StartupNotify=true
EOF
chmod 0755 "${ROOTFS_DIR}/etc/skel/Desktop/visual-studio-code.desktop"

# Apply the defaults to users that pi-gen has already created.
for HOME_DIR in "${ROOTFS_DIR}"/home/*; do
    [[ -d "${HOME_DIR}" ]] || continue
    USER_NAME="$(basename "${HOME_DIR}")"

    install -d -m 0755 "${HOME_DIR}/.config/Code/User" "${HOME_DIR}/Desktop"
    cp "${ROOTFS_DIR}/etc/skel/.config/Code/User/settings.json" "${HOME_DIR}/.config/Code/User/settings.json"
    cp "${ROOTFS_DIR}/etc/skel/Desktop/visual-studio-code.desktop" "${HOME_DIR}/Desktop/visual-studio-code.desktop"
    chmod 0755 "${HOME_DIR}/Desktop/visual-studio-code.desktop"

    USER_UID="$(chroot "${ROOTFS_DIR}" id -u "${USER_NAME}" 2>/dev/null || true)"
    USER_GID="$(chroot "${ROOTFS_DIR}" id -g "${USER_NAME}" 2>/dev/null || true)"
    if [[ -n "${USER_UID}" && -n "${USER_GID}" ]]; then
        chown -R "${USER_UID}:${USER_GID}" "${HOME_DIR}/.config/Code" "${HOME_DIR}/Desktop/visual-studio-code.desktop"
    fi
done

# Preinstall the Microsoft Python extension for the primary classroom account.
# Extension installation is non-fatal so a temporary Marketplace outage cannot
# invalidate an otherwise-good OS image. Students still have Python immediately.
on_chroot <<'EOF'
if id lg_cs_cont >/dev/null 2>&1 && command -v code >/dev/null 2>&1; then
    runuser -u lg_cs_cont -- env HOME=/home/lg_cs_cont code --install-extension ms-python.python --force || true
fi
EOF

rm -rf "${ROOTFS_DIR}/tmp/LGHS-System"

echo "LGHS: ${LGHS_ROLE} role installed for ${IMAGE_HOSTNAME}."
echo "LGHS: VS Code, Python, pip, venv, Git, and build tools installed."
