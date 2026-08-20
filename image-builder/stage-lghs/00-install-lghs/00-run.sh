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
    *cont*) LGHS_ROLE="controller" ;;
    *)      LGHS_ROLE="student" ;;
esac

echo "LGHS: detected image hostname: ${IMAGE_HOSTNAME}"
echo "LGHS: selected role: ${LGHS_ROLE}"

SOURCE_DIR="${STAGE_DIR}/00-install-lghs/files/LGHS-System"
if [[ ! -f "${SOURCE_DIR}/install.sh" ]]; then
    echo "LGHS: staged source tree is missing: ${SOURCE_DIR}" >&2
    echo "LGHS: run image-builder/build-image.sh instead of invoking pi-gen directly." >&2
    exit 1
fi

# Do not use /tmp for the staged source: pi-gen's chroot preparation can mount
# or clean temporary directories. /opt remains visible inside on_chroot.
CHROOT_SOURCE="/opt/lghs-build-source"
rm -rf "${ROOTFS_DIR}${CHROOT_SOURCE}"
mkdir -p "${ROOTFS_DIR}${CHROOT_SOURCE}"
cp -a "${SOURCE_DIR}/." "${ROOTFS_DIR}${CHROOT_SOURCE}/"
chmod 0755 "${ROOTFS_DIR}${CHROOT_SOURCE}/install.sh"

if [[ ! -f "${ROOTFS_DIR}${CHROOT_SOURCE}/install.sh" ]]; then
    echo "LGHS: failed to stage install.sh into image rootfs." >&2
    exit 1
fi

install -d -m 0755 "${ROOTFS_DIR}/etc/lghs"
printf '%s\n' "${IMAGE_HOSTNAME}" > "${ROOTFS_DIR}/etc/lghs/build-hostname"
printf '%s\n' "${LGHS_ROLE}" > "${ROOTFS_DIR}/etc/lghs/build-role"

on_chroot <<EOF
set -e
cd ${CHROOT_SOURCE}
/bin/bash ./install.sh ${LGHS_ROLE}
EOF

# Classroom development environment shared by both roles.
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

# Beginner-friendly VS Code defaults.
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
    "workbench.startupEditor": "none"
}
EOF

# Classroom working folder. No README is created.
install -d -m 0755 \
    "${ROOTFS_DIR}/etc/skel/CS2" \
    "${ROOTFS_DIR}/etc/skel/CS2/Assignments" \
    "${ROOTFS_DIR}/etc/skel/CS2/Projects" \
    "${ROOTFS_DIR}/etc/skel/CS2/My Programs"
cat > "${ROOTFS_DIR}/etc/skel/CS2/hello.py" <<'EOF'
print("Hello, world!")
EOF

# Wrapper used by the desktop icon. It opens VS Code directly in ~/CS2.
cat > "${ROOTFS_DIR}/usr/local/bin/lghs-vscode" <<'EOF'
#!/bin/sh
exec /usr/bin/code "$HOME/CS2"
EOF
chmod 0755 "${ROOTFS_DIR}/usr/local/bin/lghs-vscode"

# Desktop launcher for VS Code -> ~/CS2.
install -d -m 0755 "${ROOTFS_DIR}/etc/skel/Desktop"
cat > "${ROOTFS_DIR}/etc/skel/Desktop/visual-studio-code.desktop" <<'EOF'
[Desktop Entry]
Version=1.0
Type=Application
Name=Visual Studio Code
Comment=Open the CS2 Python folder
Exec=/usr/local/bin/lghs-vscode
Icon=visual-studio-code
Terminal=false
Categories=Development;IDE;
StartupNotify=true
EOF
chmod 0755 "${ROOTFS_DIR}/etc/skel/Desktop/visual-studio-code.desktop"

# Apply the same classroom defaults to users pi-gen already created.
for HOME_DIR in "${ROOTFS_DIR}"/home/*; do
    [[ -d "${HOME_DIR}" ]] || continue
    USER_NAME="$(basename "${HOME_DIR}")"

    install -d -m 0755 \
        "${HOME_DIR}/.config/Code/User" \
        "${HOME_DIR}/Desktop" \
        "${HOME_DIR}/CS2" \
        "${HOME_DIR}/CS2/Assignments" \
        "${HOME_DIR}/CS2/Projects" \
        "${HOME_DIR}/CS2/My Programs"

    cp "${ROOTFS_DIR}/etc/skel/.config/Code/User/settings.json" "${HOME_DIR}/.config/Code/User/settings.json"
    cp "${ROOTFS_DIR}/etc/skel/Desktop/visual-studio-code.desktop" "${HOME_DIR}/Desktop/visual-studio-code.desktop"
    cp "${ROOTFS_DIR}/etc/skel/CS2/hello.py" "${HOME_DIR}/CS2/hello.py"
    chmod 0755 "${HOME_DIR}/Desktop/visual-studio-code.desktop"

    USER_UID="$(chroot "${ROOTFS_DIR}" id -u "${USER_NAME}" 2>/dev/null || true)"
    USER_GID="$(chroot "${ROOTFS_DIR}" id -g "${USER_NAME}" 2>/dev/null || true)"
    if [[ -n "${USER_UID}" && -n "${USER_GID}" ]]; then
        chown -R "${USER_UID}:${USER_GID}" \
            "${HOME_DIR}/.config/Code" \
            "${HOME_DIR}/Desktop/visual-studio-code.desktop" \
            "${HOME_DIR}/CS2"
    fi
done

# Preinstall the Microsoft Python extension for the primary classroom account.
# A Marketplace outage does not fail the OS image build.
on_chroot <<'EOF'
if id lg_cs_cont >/dev/null 2>&1 && command -v code >/dev/null 2>&1; then
    runuser -u lg_cs_cont -- env HOME=/home/lg_cs_cont code --install-extension ms-python.python --force || true
fi
EOF

rm -rf "${ROOTFS_DIR}${CHROOT_SOURCE}"

echo "LGHS: ${LGHS_ROLE} role installed for ${IMAGE_HOSTNAME}."
echo "LGHS: VS Code opens ~/CS2 with hello.py and classroom folders ready."
