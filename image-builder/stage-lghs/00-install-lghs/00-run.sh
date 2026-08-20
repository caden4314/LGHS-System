#!/bin/bash -e

HOSTNAME_FILE="${ROOTFS_DIR}/etc/hostname"
[[ -f "$HOSTNAME_FILE" ]] || { echo "LGHS: missing $HOSTNAME_FILE" >&2; exit 1; }
IMAGE_HOSTNAME="$(tr -d '[:space:]' < "$HOSTNAME_FILE")"
IMAGE_HOSTNAME_LOWER="$(printf '%s' "$IMAGE_HOSTNAME" | tr '[:upper:]' '[:lower:]')"
[[ -n "$IMAGE_HOSTNAME" ]] || { echo "LGHS: image hostname is empty" >&2; exit 1; }
case "$IMAGE_HOSTNAME_LOWER" in *cont*) LGHS_ROLE="controller" ;; *) LGHS_ROLE="student" ;; esac

echo "LGHS: detected image hostname: ${IMAGE_HOSTNAME}"
echo "LGHS: selected role: ${LGHS_ROLE}"

SOURCE_DIR="${STAGE_DIR}/00-install-lghs/files/LGHS-System"
KEY_DIR="${STAGE_DIR}/00-install-lghs/files/fleet-keys"
[[ -f "$SOURCE_DIR/install.sh" ]] || { echo "LGHS: staged source missing" >&2; exit 1; }
[[ -f "$KEY_DIR/controller_ed25519.pub" ]] || { echo "LGHS: fleet public key missing; use build-image.sh" >&2; exit 1; }

CHROOT_SOURCE="/opt/lghs-build-source"
rm -rf "${ROOTFS_DIR}${CHROOT_SOURCE}"
mkdir -p "${ROOTFS_DIR}${CHROOT_SOURCE}"
cp -a "$SOURCE_DIR/." "${ROOTFS_DIR}${CHROOT_SOURCE}/"
chmod 0755 "${ROOTFS_DIR}${CHROOT_SOURCE}/install.sh"

install -d -m 0755 "${ROOTFS_DIR}/etc/lghs"
install -d -m 0700 "${ROOTFS_DIR}/etc/lghs/secrets"
printf '%s\n' "$IMAGE_HOSTNAME" > "${ROOTFS_DIR}/etc/lghs/build-hostname"
printf '%s\n' "$LGHS_ROLE" > "${ROOTFS_DIR}/etc/lghs/build-role"

install -m 0644 "$KEY_DIR/controller_ed25519.pub" "${ROOTFS_DIR}/etc/lghs/controller_ed25519.pub"
if [[ "$LGHS_ROLE" == "controller" ]]; then
    install -m 0600 "$KEY_DIR/controller_ed25519" "${ROOTFS_DIR}/etc/lghs/secrets/controller_ed25519"
    install -m 0644 "$KEY_DIR/controller_ed25519.pub" "${ROOTFS_DIR}/etc/lghs/secrets/controller_ed25519.pub"
fi

on_chroot <<EOF
set -e
cd ${CHROOT_SOURCE}
/bin/bash ./install.sh ${LGHS_ROLE}
if [[ "${LGHS_ROLE}" == "student" ]]; then
    /bin/bash ./student/lghs-install-network-ui
fi
EOF

on_chroot <<'EOF'
apt-get update
DEBIAN_FRONTEND=noninteractive apt-get install -y \
    code python3 python3-pip python3-venv python3-dev pipx git build-essential
EOF

install -d -m 0755 "${ROOTFS_DIR}/etc/skel/.config/Code/User"
cat > "${ROOTFS_DIR}/etc/skel/.config/Code/User/settings.json" <<'EOF'
{
    "python.defaultInterpreterPath": "${workspaceFolder}/.venv/bin/python",
    "python.terminal.activateEnvironment": true,
    "python.createEnvironment.trigger": "off",
    "python.analysis.autoImportCompletions": true,
    "terminal.integrated.defaultProfile.linux": "bash",
    "files.autoSave": "afterDelay",
    "files.autoSaveDelay": 1000,
    "editor.formatOnSave": false,
    "workbench.startupEditor": "none"
}
EOF

install -d -m 0755 "${ROOTFS_DIR}/etc/skel/CS2" "${ROOTFS_DIR}/etc/skel/CS2/Assignments" "${ROOTFS_DIR}/etc/skel/CS2/Projects" "${ROOTFS_DIR}/etc/skel/CS2/My Programs"
cat > "${ROOTFS_DIR}/etc/skel/CS2/hello.py" <<'EOF'
print("Hello, world!")
EOF

cat > "${ROOTFS_DIR}/usr/local/bin/lghs-vscode" <<'EOF'
#!/bin/sh
exec /usr/bin/code "$HOME/CS2"
EOF
chmod 0755 "${ROOTFS_DIR}/usr/local/bin/lghs-vscode"

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

for HOME_DIR in "${ROOTFS_DIR}"/home/*; do
    [[ -d "$HOME_DIR" ]] || continue
    USER_NAME="$(basename "$HOME_DIR")"
    install -d -m 0755 "$HOME_DIR/.config/Code/User" "$HOME_DIR/Desktop" "$HOME_DIR/CS2" "$HOME_DIR/CS2/Assignments" "$HOME_DIR/CS2/Projects" "$HOME_DIR/CS2/My Programs"
    cp "${ROOTFS_DIR}/etc/skel/.config/Code/User/settings.json" "$HOME_DIR/.config/Code/User/settings.json"
    cp "${ROOTFS_DIR}/etc/skel/Desktop/visual-studio-code.desktop" "$HOME_DIR/Desktop/visual-studio-code.desktop"
    cp "${ROOTFS_DIR}/etc/skel/CS2/hello.py" "$HOME_DIR/CS2/hello.py"
    chmod 0755 "$HOME_DIR/Desktop/visual-studio-code.desktop"
    USER_UID="$(chroot "$ROOTFS_DIR" id -u "$USER_NAME" 2>/dev/null || true)"
    USER_GID="$(chroot "$ROOTFS_DIR" id -g "$USER_NAME" 2>/dev/null || true)"
    if [[ -n "$USER_UID" && -n "$USER_GID" ]]; then chown -R "$USER_UID:$USER_GID" "$HOME_DIR/.config/Code" "$HOME_DIR/Desktop/visual-studio-code.desktop" "$HOME_DIR/CS2"; fi
done

on_chroot <<EOF
if [[ "${LGHS_ROLE}" == "student" ]]; then
    /usr/local/sbin/lghs-dev-setup
elif command -v code >/dev/null 2>&1 && id lg_cs_cont >/dev/null 2>&1; then
    runuser -u lg_cs_cont -- env HOME=/home/lg_cs_cont code --install-extension ms-python.python --force || true
fi
EOF

rm -rf "${ROOTFS_DIR}${CHROOT_SOURCE}"
echo "LGHS: ${LGHS_ROLE} role installed for ${IMAGE_HOSTNAME}."
echo "LGHS: first-boot Imager provisioning enabled."
echo "LGHS: fleet SSH enrollment configured."
if [[ "$LGHS_ROLE" == "student" ]]; then
    echo "LGHS: restricted NetworkManager panel UI installed for lg_cs_cont."
    echo "LGHS: teacher-approved sudo queue and audit logging installed."
    echo "LGHS: student Python venv/pip and VS Code environment prepared."
fi
echo "LGHS: VS Code opens ~/CS2 with hello.py and classroom folders ready."
