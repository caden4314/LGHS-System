#!/usr/bin/env bash
set -euo pipefail

ROLE="${1:-}"
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [[ $EUID -ne 0 ]]; then echo "Run as root: sudo ./install.sh <controller|student>" >&2; exit 1; fi
if [[ "$ROLE" != "controller" && "$ROLE" != "student" ]]; then echo "Usage: sudo ./install.sh <controller|student>" >&2; exit 2; fi

install -d -m 0755 /opt/lghs /etc/lghs /var/lib/lghs /var/lib/lghs/update
install -d -m 0700 /etc/lghs/secrets /var/lib/lghs/netqueue /var/lib/lghs/netqueue/jobs
printf '%s\n' "$ROLE" > /etc/lghs/role
printf '%s\n' "$(cat "$ROOT_DIR/VERSION")" > /etc/lghs/version

SOURCE_COMMIT="unknown"
if [[ -f "$ROOT_DIR/.lghs-source-commit" ]]; then SOURCE_COMMIT="$(tr -d '[:space:]' < "$ROOT_DIR/.lghs-source-commit")";
elif [[ -d "$ROOT_DIR/.git" ]]; then SOURCE_COMMIT="$(git -C "$ROOT_DIR" rev-parse HEAD 2>/dev/null || echo unknown)"; fi
if [[ -n "$SOURCE_COMMIT" && "$SOURCE_COMMIT" != "unknown" ]]; then
  printf '%s\n' "$SOURCE_COMMIT" > /etc/lghs/source-commit
  printf '%s\n' "$SOURCE_COMMIT" > /var/lib/lghs/update/current-commit
fi

install -m 0755 "$ROOT_DIR/updater/lghs-update" /usr/local/sbin/lghs-update
install -m 0755 "$ROOT_DIR/updater/lghs-os-update" /usr/local/sbin/lghs-os-update
install -m 0755 "$ROOT_DIR/updater/lghs-autologin-apply" /usr/local/sbin/lghs-autologin-apply
install -m 0755 "$ROOT_DIR/updater/lghs-reconcile" /usr/local/sbin/lghs-reconcile
install -m 0755 "$ROOT_DIR/updater/lghs-access-enforce" /usr/local/sbin/lghs-access-enforce
install -m 0755 "$ROOT_DIR/updater/lghs-netqueue" /usr/local/sbin/lghs-netqueue
install -m 0755 "$ROOT_DIR/student/lghs-report" /usr/local/sbin/lghs-report
install -m 0755 "$ROOT_DIR/student/lghs-firstboot-provision" /usr/local/sbin/lghs-firstboot-provision
install -m 0755 "$ROOT_DIR/student/lghs-dev-setup" /usr/local/sbin/lghs-dev-setup
install -m 0644 "$ROOT_DIR/systemd/lghs-update.service" /etc/systemd/system/lghs-update.service
install -m 0644 "$ROOT_DIR/systemd/lghs-update.timer" /etc/systemd/system/lghs-update.timer
install -m 0644 "$ROOT_DIR/systemd/lghs-firstboot-provision.service" /etc/systemd/system/lghs-firstboot-provision.service
install -m 0644 "$ROOT_DIR/systemd/lghs-reconcile.service" /etc/systemd/system/lghs-reconcile.service
install -m 0644 "$ROOT_DIR/systemd/lghs-reconcile.timer" /etc/systemd/system/lghs-reconcile.timer
install -m 0644 "$ROOT_DIR/systemd/lghs-netqueue.service" /etc/systemd/system/lghs-netqueue.service
install -m 0644 "$ROOT_DIR/systemd/lghs-netqueue.timer" /etc/systemd/system/lghs-netqueue.timer
install -d -m 0755 /etc/NetworkManager/dispatcher.d
install -m 0755 "$ROOT_DIR/systemd/90-lghs-netqueue" /etc/NetworkManager/dispatcher.d/90-lghs-netqueue
install -m 0440 "$ROOT_DIR/policies/sudoers/89-lghs-audit" /etc/sudoers.d/89-lghs-audit

touch /var/log/lghs-netqueue.log
chown root:adm /var/log/lghs-netqueue.log 2>/dev/null || true
chmod 0640 /var/log/lghs-netqueue.log

COMMON_PKGS=(git curl python3 openssh-client sudo logrotate)
if ! command -v flock >/dev/null 2>&1; then COMMON_PKGS+=(util-linux); fi
MISSING_PKGS=()
for pkg in "${COMMON_PKGS[@]}"; do dpkg-query -W -f='${Status}' "$pkg" 2>/dev/null | grep -q 'ok installed' || MISSING_PKGS+=("$pkg"); done
if (( ${#MISSING_PKGS[@]} )); then apt-get update; DEBIAN_FRONTEND=noninteractive apt-get install -y "${MISSING_PKGS[@]}"; fi

if ! id cs_admin >/dev/null 2>&1; then useradd -m -s /bin/bash cs_admin; fi
usermod -aG sudo cs_admin
install -d -m 0700 -o cs_admin -g cs_admin /home/cs_admin/.ssh
cat > /etc/sudoers.d/91-lghs-admin <<'EOF'
Defaults:cs_admin timestamp_timeout=5
cs_admin ALL=(ALL:ALL) ALL
cs_admin ALL=(root) NOPASSWD: /usr/local/sbin/lghs-report *
cs_admin ALL=(root) NOPASSWD: /usr/local/sbin/lghs-update
cs_admin ALL=(root) NOPASSWD: /usr/local/sbin/lghs-os-update
cs_admin ALL=(root) NOPASSWD: /usr/local/sbin/lghs-os-update --reboot
cs_admin ALL=(root) NOPASSWD: /usr/local/sbin/lghs-check
cs_admin ALL=(root) NOPASSWD: /usr/local/sbin/lghs-enforce
cs_admin ALL=(root) NOPASSWD: /usr/local/sbin/lghs-sudo-admin *
cs_admin ALL=(root) NOPASSWD: /usr/local/sbin/lghs-audit-export *
cs_admin ALL=(root) NOPASSWD: /usr/local/sbin/lghs-audit-sync
cs_admin ALL=(root) NOPASSWD: /usr/sbin/reboot
cs_admin ALL=(root) NOPASSWD: /usr/sbin/poweroff
cs_admin ALL=(root) NOPASSWD: /usr/sbin/shutdown
EOF
chmod 0440 /etc/sudoers.d/91-lghs-admin

if [[ "$ROLE" == "controller" ]]; then
  install -d -m 0755 /usr/local/libexec
  install -m 0755 "$ROOT_DIR/controller/lghsctl" /usr/local/libexec/lghsctl-real
  install -m 0755 "$ROOT_DIR/controller/lghsctl-wrapper" /usr/local/sbin/lghsctl

  # Keep the complete original console implementation as a module and install a
  # thin responsive launcher that performs discovery/SSH refresh in background
  # workers instead of blocking curses keyboard input.
  install -m 0755 "$ROOT_DIR/controller/lghs-console" /usr/local/libexec/lghs-console-base
  install -m 0755 "$ROOT_DIR/controller/lghs-console-responsive" /usr/local/sbin/lghs-console
  install -m 0755 "$ROOT_DIR/controller/lghs-fleet-notify" /usr/local/sbin/lghs-fleet-notify
  install -m 0644 "$ROOT_DIR/systemd/lghs-fleet-notify.service" /etc/systemd/system/lghs-fleet-notify.service

  install -m 0755 "$ROOT_DIR/controller/lghs-audit-sync" /usr/local/sbin/lghs-audit-sync
  install -m 0644 "$ROOT_DIR/systemd/lghs-audit-sync.service" /etc/systemd/system/lghs-audit-sync.service
  install -m 0644 "$ROOT_DIR/systemd/lghs-audit-sync.timer" /etc/systemd/system/lghs-audit-sync.timer

  CTRL_PKGS=(avahi-daemon avahi-utils libnotify-bin)
  MISSING_PKGS=()
  for pkg in "${CTRL_PKGS[@]}"; do dpkg-query -W -f='${Status}' "$pkg" 2>/dev/null | grep -q 'ok installed' || MISSING_PKGS+=("$pkg"); done
  if (( ${#MISSING_PKGS[@]} )); then apt-get update; DEBIAN_FRONTEND=noninteractive apt-get install -y "${MISSING_PKGS[@]}"; fi

  KEY_FILE=/etc/lghs/secrets/controller_ed25519
  if [[ "${LGHS_IMAGE_BUILD:-0}" == "1" ]]; then
    rm -f "$KEY_FILE" "$KEY_FILE.pub" /etc/lghs/controller_ed25519.pub
    echo 'LGHS image build: controller fleet key generation suppressed.'
  else
    if [[ ! -f "$KEY_FILE" ]]; then ssh-keygen -q -t ed25519 -N '' -C 'LGHS fleet controller' -f "$KEY_FILE"; fi
    chmod 0600 "$KEY_FILE"; chmod 0644 "$KEY_FILE.pub"
    install -m 0644 "$KEY_FILE.pub" /etc/lghs/controller_ed25519.pub
  fi
  touch /var/lib/lghs/ssh_known_hosts; chmod 0644 /var/lib/lghs/ssh_known_hosts
  install -d -m 0750 -o root -g adm /var/log/lghs-fleet
  cat > /etc/logrotate.d/lghs-fleet <<'EOF'
/var/log/lghs-fleet/*.log /var/log/lghs-fleet/*.jsonl /var/log/lghs-fleet/*/*.log /var/log/lghs-fleet/*/*.jsonl {
    weekly
    rotate 16
    compress
    delaycompress
    missingok
    notifempty
    create 0640 root adm
}
EOF
  chmod 0644 /etc/logrotate.d/lghs-fleet
else
  install -m 0755 "$ROOT_DIR/student/lghs-enforce" /usr/local/sbin/lghs-enforce
  install -m 0755 "$ROOT_DIR/student/lghs-check" /usr/local/sbin/lghs-check
  install -m 0755 "$ROOT_DIR/student/lghs-agent" /usr/local/sbin/lghs-agent
  install -m 0755 "$ROOT_DIR/student/lghs-network-ui-apply" /usr/local/sbin/lghs-network-ui-apply
  install -m 0755 "$ROOT_DIR/student/lghs-install-network-ui" /usr/local/sbin/lghs-install-network-ui
  install -m 0755 "$ROOT_DIR/student/lghs-sudo-broker" /usr/local/sbin/lghs-sudo-broker
  install -m 0755 "$ROOT_DIR/student/lghs-approved-exec" /usr/local/sbin/lghs-approved-exec
  install -m 0755 "$ROOT_DIR/student/lghs-sudo-admin" /usr/local/sbin/lghs-sudo-admin
  install -m 0755 "$ROOT_DIR/student/lghs-audit-export" /usr/local/sbin/lghs-audit-export
  install -m 0755 "$ROOT_DIR/student/sudo" /usr/local/bin/sudo
  install -d -m 0700 /var/lib/lghs/sudo-requests
  touch /var/log/lghs-sudo-audit.jsonl /var/log/sudo.log /var/log/lghs-update.log /var/log/lghs-os-update.log
  chown root:adm /var/log/lghs-sudo-audit.jsonl /var/log/sudo.log /var/log/lghs-update.log /var/log/lghs-os-update.log 2>/dev/null || true
  chmod 0640 /var/log/lghs-sudo-audit.jsonl /var/log/sudo.log /var/log/lghs-update.log /var/log/lghs-os-update.log

  install -m 0440 "$ROOT_DIR/policies/sudoers/90-lghs-student" /etc/sudoers.d/90-lghs-student
  install -m 0644 "$ROOT_DIR/policies/polkit/49-lghs-network.rules" /etc/polkit-1/rules.d/49-lghs-network.rules

  STUDENT_PKGS=(openssh-server network-manager policykit-1 avahi-daemon avahi-utils)
  MISSING_PKGS=()
  for pkg in "${STUDENT_PKGS[@]}"; do dpkg-query -W -f='${Status}' "$pkg" 2>/dev/null | grep -q 'ok installed' || MISSING_PKGS+=("$pkg"); done
  if (( ${#MISSING_PKGS[@]} )); then apt-get update; DEBIAN_FRONTEND=noninteractive apt-get install -y "${MISSING_PKGS[@]}"; fi

  if [[ -f /etc/lghs/controller_ed25519.pub ]]; then install -m 0600 -o cs_admin -g cs_admin /etc/lghs/controller_ed25519.pub /home/cs_admin/.ssh/authorized_keys; fi

  install -d -m 0755 /etc/ssh/sshd_config.d
  cat > /etc/ssh/sshd_config.d/90-lghs-fleet.conf <<'EOF'
Match User cs_admin
    AuthenticationMethods publickey
    PasswordAuthentication no
    KbdInteractiveAuthentication no
    PubkeyAuthentication yes
    X11Forwarding no
    AllowAgentForwarding no
    AllowTcpForwarding no
    PermitTunnel no
    GatewayPorts no
EOF
  chmod 0644 /etc/ssh/sshd_config.d/90-lghs-fleet.conf
  sshd -t
  install -m 0644 "$ROOT_DIR/systemd/lghs-policy.service" /etc/systemd/system/lghs-policy.service
  install -m 0644 "$ROOT_DIR/systemd/lghs-agent.service" /etc/systemd/system/lghs-agent.service

  if [[ ! -f /usr/local/lib/lghs/libnetman.so.hardened ]]; then /usr/local/sbin/lghs-install-network-ui; else /usr/local/sbin/lghs-network-ui-apply; fi
fi

/usr/local/sbin/lghs-dev-setup
/usr/local/sbin/lghs-autologin-apply || true

visudo -cf /etc/sudoers >/dev/null
systemctl daemon-reload

# Enable AND start timers immediately. Using only `enable` left fresh installs
# showing inactive timers until a later reboot.
systemctl enable lghs-update.service lghs-firstboot-provision.service avahi-daemon.service
systemctl enable --now lghs-update.timer lghs-reconcile.timer lghs-netqueue.timer
if [[ "$ROLE" == "student" ]]; then
  systemctl enable --now lghs-policy.service lghs-agent.service ssh.service
else
  systemctl enable --now lghs-audit-sync.timer lghs-fleet-notify.service
fi

/usr/local/sbin/lghs-access-enforce

if systemctl is-system-running --quiet 2>/dev/null || systemctl is-system-running 2>/dev/null | grep -Eq 'running|degraded'; then
  systemctl try-restart avahi-daemon.service || true
  systemctl start --no-block lghs-netqueue.service >/dev/null 2>&1 || true
fi

echo "LGHS $ROLE installation completed."
