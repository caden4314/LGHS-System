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

install -d -m 0755 /opt/lghs /etc/lghs /var/lib/lghs
install -d -m 0700 /etc/lghs/secrets
printf '%s\n' "$ROLE" > /etc/lghs/role
printf '%s\n' "$(cat "$ROOT_DIR/VERSION")" > /etc/lghs/version

if [[ "$ROLE" == "controller" ]]; then
  install -m 0755 "$ROOT_DIR/controller/lghsctl" /usr/local/sbin/lghsctl
  apt-get update
  apt-get install -y openssh-client avahi-utils python3
else
  install -m 0755 "$ROOT_DIR/student/lghs-enforce" /usr/local/sbin/lghs-enforce
  install -m 0755 "$ROOT_DIR/student/lghs-check" /usr/local/sbin/lghs-check
  install -m 0755 "$ROOT_DIR/student/lghs-agent" /usr/local/sbin/lghs-agent

  install -m 0440 "$ROOT_DIR/policies/sudoers/90-lghs-student" /etc/sudoers.d/90-lghs-student
  install -m 0644 "$ROOT_DIR/policies/polkit/49-lghs-network.rules" /etc/polkit-1/rules.d/49-lghs-network.rules

  visudo -cf /etc/sudoers >/dev/null

  install -m 0644 "$ROOT_DIR/systemd/lghs-policy.service" /etc/systemd/system/lghs-policy.service
  install -m 0644 "$ROOT_DIR/systemd/lghs-agent.service" /etc/systemd/system/lghs-agent.service

  apt-get update
  apt-get install -y openssh-server network-manager policykit-1 avahi-daemon avahi-utils python3

  systemctl daemon-reload
  systemctl enable lghs-policy.service lghs-agent.service avahi-daemon ssh
fi

echo "LGHS $ROLE installation completed."
