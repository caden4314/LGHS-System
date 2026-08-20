#!/usr/bin/env bash
set -euo pipefail

ROLE="${1:-}"
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [[ $EUID -ne 0 ]]; then
  echo "Run as root: sudo ./install.sh <controller|student>" >&2
  exit 1
fi
if [[ "$ROLE" != "controller" && "$ROLE" != "student" ]]; then
  echo "Usage: sudo ./install.sh <controller|student>" >&2
  exit 2
fi

install -d -m 0755 /opt/lghs /etc/lghs /var/lib/lghs /var/lib/lghs/update
install -d -m 0700 /etc/lghs/secrets
printf '%s\n' "$ROLE" > /etc/lghs/role
printf '%s\n' "$(cat "$ROOT_DIR/VERSION")" > /etc/lghs/version

SOURCE_COMMIT="unknown"
if [[ -f "$ROOT_DIR/.lghs-source-commit" ]]; then
  SOURCE_COMMIT="$(tr -d '[:space:]' < "$ROOT_DIR/.lghs-source-commit")"
elif [[ -d "$ROOT_DIR/.git" ]]; then
  SOURCE_COMMIT="$(git -C "$ROOT_DIR" rev-parse HEAD 2>/dev/null || echo unknown)"
fi
if [[ -n "$SOURCE_COMMIT" && "$SOURCE_COMMIT" != "unknown" ]]; then
  printf '%s\n' "$SOURCE_COMMIT" > /etc/lghs/source-commit
  printf '%s\n' "$SOURCE_COMMIT" > /var/lib/lghs/update/current-commit
fi

# Common management and live-update components.
install -m 0755 "$ROOT_DIR/updater/lghs-update" /usr/local/sbin/lghs-update
install -m 0755 "$ROOT_DIR/student/lghs-report" /usr/local/sbin/lghs-report
install -m 0644 "$ROOT_DIR/systemd/lghs-update.service" /etc/systemd/system/lghs-update.service
install -m 0644 "$ROOT_DIR/systemd/lghs-update.timer" /etc/systemd/system/lghs-update.timer

COMMON_PKGS=(git curl python3 openssh-client)
if ! command -v flock >/dev/null 2>&1; then COMMON_PKGS+=(util-linux); fi
MISSING_PKGS=()
for pkg in "${COMMON_PKGS[@]}"; do
  dpkg-query -W -f='${Status}' "$pkg" 2>/dev/null | grep -q 'ok installed' || MISSING_PKGS+=("$pkg")
done
if (( ${#MISSING_PKGS[@]} )); then
  apt-get update
  DEBIAN_FRONTEND=noninteractive apt-get install -y "${MISSING_PKGS[@]}"
fi

# Dedicated key-only fleet administration account. Password login is locked.
if ! id cs_admin >/dev/null 2>&1; then
  useradd -m -s /bin/bash cs_admin
fi
usermod -aG sudo cs_admin
passwd -l cs_admin >/dev/null 2>&1 || true
install -d -m 0700 -o cs_admin -g cs_admin /home/cs_admin/.ssh
cat > /etc/sudoers.d/91-lghs-admin <<'EOF'
cs_admin ALL=(ALL) NOPASSWD: ALL
EOF
chmod 0440 /etc/sudoers.d/91-lghs-admin
visudo -cf /etc/sudoers >/dev/null

if [[ "$ROLE" == "controller" ]]; then
  install -m 0755 "$ROOT_DIR/controller/lghsctl" /usr/local/sbin/lghsctl
  install -m 0755 "$ROOT_DIR/controller/lghs-console" /usr/local/sbin/lghs-console

  CTRL_PKGS=(avahi-daemon avahi-utils)
  MISSING_PKGS=()
  for pkg in "${CTRL_PKGS[@]}"; do
    dpkg-query -W -f='${Status}' "$pkg" 2>/dev/null | grep -q 'ok installed' || MISSING_PKGS+=("$pkg")
  done
  if (( ${#MISSING_PKGS[@]} )); then
    apt-get update
    DEBIAN_FRONTEND=noninteractive apt-get install -y "${MISSING_PKGS[@]}"
  fi

  # The image builder injects the fleet private key. Manual controller installs
  # create one locally. The private key never belongs in Git.
  KEY_FILE=/etc/lghs/secrets/controller_ed25519
  if [[ ! -f "$KEY_FILE" ]]; then
    ssh-keygen -q -t ed25519 -N '' -C 'LGHS fleet controller' -f "$KEY_FILE"
  fi
  chmod 0600 "$KEY_FILE"
  chmod 0644 "$KEY_FILE.pub"
  install -m 0644 "$KEY_FILE.pub" /etc/lghs/controller_ed25519.pub
else
  install -m 0755 "$ROOT_DIR/student/lghs-enforce" /usr/local/sbin/lghs-enforce
  install -m 0755 "$ROOT_DIR/student/lghs-check" /usr/local/sbin/lghs-check
  install -m 0755 "$ROOT_DIR/student/lghs-agent" /usr/local/sbin/lghs-agent

  install -m 0440 "$ROOT_DIR/policies/sudoers/90-lghs-student" /etc/sudoers.d/90-lghs-student
  install -m 0644 "$ROOT_DIR/policies/polkit/49-lghs-network.rules" /etc/polkit-1/rules.d/49-lghs-network.rules

  STUDENT_PKGS=(openssh-server network-manager policykit-1 avahi-daemon avahi-utils)
  MISSING_PKGS=()
  for pkg in "${STUDENT_PKGS[@]}"; do
    dpkg-query -W -f='${Status}' "$pkg" 2>/dev/null | grep -q 'ok installed' || MISSING_PKGS+=("$pkg")
  done
  if (( ${#MISSING_PKGS[@]} )); then
    apt-get update
    DEBIAN_FRONTEND=noninteractive apt-get install -y "${MISSING_PKGS[@]}"
  fi

  # Student images receive only the controller public key.
  if [[ -f /etc/lghs/controller_ed25519.pub ]]; then
    install -m 0600 -o cs_admin -g cs_admin /etc/lghs/controller_ed25519.pub /home/cs_admin/.ssh/authorized_keys
  fi

  install -m 0644 "$ROOT_DIR/systemd/lghs-policy.service" /etc/systemd/system/lghs-policy.service
  install -m 0644 "$ROOT_DIR/systemd/lghs-agent.service" /etc/systemd/system/lghs-agent.service
fi

systemctl daemon-reload
systemctl enable lghs-update.service lghs-update.timer avahi-daemon.service
if [[ "$ROLE" == "student" ]]; then
  systemctl enable lghs-policy.service lghs-agent.service ssh
fi

if systemctl is-system-running --quiet 2>/dev/null || systemctl is-system-running 2>/dev/null | grep -Eq 'running|degraded'; then
  systemctl try-restart avahi-daemon.service || true
  if [[ "$ROLE" == "student" ]]; then
    systemctl try-restart lghs-policy.service lghs-agent.service ssh.service || true
  fi
fi

echo "LGHS $ROLE installation completed."
