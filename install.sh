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

# Common live-update components for both controller and student systems.
install -m 0755 "$ROOT_DIR/updater/lghs-update" /usr/local/sbin/lghs-update
install -m 0644 "$ROOT_DIR/systemd/lghs-update.service" /etc/systemd/system/lghs-update.service
install -m 0644 "$ROOT_DIR/systemd/lghs-update.timer" /etc/systemd/system/lghs-update.timer

COMMON_PKGS=(git curl python3)
if ! command -v flock >/dev/null 2>&1; then
  COMMON_PKGS+=(util-linux)
fi

MISSING_PKGS=()
for pkg in "${COMMON_PKGS[@]}"; do
  dpkg-query -W -f='${Status}' "$pkg" 2>/dev/null | grep -q 'ok installed' || MISSING_PKGS+=("$pkg")
done
if (( ${#MISSING_PKGS[@]} )); then
  apt-get update
  DEBIAN_FRONTEND=noninteractive apt-get install -y "${MISSING_PKGS[@]}"
fi

if [[ "$ROLE" == "controller" ]]; then
  install -m 0755 "$ROOT_DIR/controller/lghsctl" /usr/local/sbin/lghsctl

  CTRL_PKGS=(openssh-client avahi-utils)
  MISSING_PKGS=()
  for pkg in "${CTRL_PKGS[@]}"; do
    dpkg-query -W -f='${Status}' "$pkg" 2>/dev/null | grep -q 'ok installed' || MISSING_PKGS+=("$pkg")
  done
  if (( ${#MISSING_PKGS[@]} )); then
    apt-get update
    DEBIAN_FRONTEND=noninteractive apt-get install -y "${MISSING_PKGS[@]}"
  fi
else
  install -m 0755 "$ROOT_DIR/student/lghs-enforce" /usr/local/sbin/lghs-enforce
  install -m 0755 "$ROOT_DIR/student/lghs-check" /usr/local/sbin/lghs-check
  install -m 0755 "$ROOT_DIR/student/lghs-agent" /usr/local/sbin/lghs-agent

  install -m 0440 "$ROOT_DIR/policies/sudoers/90-lghs-student" /etc/sudoers.d/90-lghs-student
  install -m 0644 "$ROOT_DIR/policies/polkit/49-lghs-network.rules" /etc/polkit-1/rules.d/49-lghs-network.rules
  visudo -cf /etc/sudoers >/dev/null

  install -m 0644 "$ROOT_DIR/systemd/lghs-policy.service" /etc/systemd/system/lghs-policy.service
  install -m 0644 "$ROOT_DIR/systemd/lghs-agent.service" /etc/systemd/system/lghs-agent.service

  STUDENT_PKGS=(openssh-server network-manager policykit-1 avahi-daemon avahi-utils)
  MISSING_PKGS=()
  for pkg in "${STUDENT_PKGS[@]}"; do
    dpkg-query -W -f='${Status}' "$pkg" 2>/dev/null | grep -q 'ok installed' || MISSING_PKGS+=("$pkg")
  done
  if (( ${#MISSING_PKGS[@]} )); then
    apt-get update
    DEBIAN_FRONTEND=noninteractive apt-get install -y "${MISSING_PKGS[@]}"
  fi
fi

systemctl daemon-reload
systemctl enable lghs-update.service lghs-update.timer

if [[ "$ROLE" == "student" ]]; then
  systemctl enable lghs-policy.service lghs-agent.service avahi-daemon ssh
fi

# During a live reinstall, immediately refresh already-running LGHS services.
if systemctl is-system-running --quiet 2>/dev/null || systemctl is-system-running 2>/dev/null | grep -Eq 'running|degraded'; then
  if [[ "$ROLE" == "student" ]]; then
    systemctl try-restart lghs-policy.service lghs-agent.service || true
  fi
fi

echo "LGHS $ROLE installation completed."
