#!/usr/bin/env bash
set -euo pipefail

ROLE="${1:-}"
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ADMIN_GROUP=lghs-admin

if [[ $EUID -ne 0 ]]; then echo "Run as root: sudo ./install.sh <controller|student>" >&2; exit 1; fi
if [[ "$ROLE" != "controller" && "$ROLE" != "student" ]]; then echo "Usage: sudo ./install.sh <controller|student>" >&2; exit 2; fi

getent group "$ADMIN_GROUP" >/dev/null 2>&1 || groupadd --system "$ADMIN_GROUP"
install -d -o root -g "$ADMIN_GROUP" -m 0750 /opt/lghs /etc/lghs /var/lib/lghs /var/lib/lghs/update
install -d -m 0700 /etc/lghs/secrets /var/lib/lghs/netqueue /var/lib/lghs/netqueue/jobs
install -d -m 0755 /usr/local/lib/lghs-bt
printf '%s\n' "$ROLE" > /etc/lghs/role
printf '%s\n' "$(cat "$ROOT_DIR/VERSION")" > /etc/lghs/version

SOURCE_COMMIT="unknown"
if [[ -f "$ROOT_DIR/.lghs-source-commit" ]]; then SOURCE_COMMIT="$(tr -d '[:space:]' < "$ROOT_DIR/.lghs-source-commit")";
elif [[ -d "$ROOT_DIR/.git" ]]; then SOURCE_COMMIT="$(git -C "$ROOT_DIR" rev-parse HEAD 2>/dev/null || echo unknown)"; fi
if [[ -n "$SOURCE_COMMIT" && "$SOURCE_COMMIT" != "unknown" ]]; then
  printf '%s\n' "$SOURCE_COMMIT" > /etc/lghs/source-commit
  printf '%s\n' "$SOURCE_COMMIT" > /var/lib/lghs/update/current-commit
fi

install -o root -g "$ADMIN_GROUP" -m 0750 "$ROOT_DIR/updater/lghs-update" /usr/local/sbin/lghs-update
install -o root -g "$ADMIN_GROUP" -m 0750 "$ROOT_DIR/updater/lghs-os-update" /usr/local/sbin/lghs-os-update
install -o root -g "$ADMIN_GROUP" -m 0750 "$ROOT_DIR/updater/lghs-autologin-apply" /usr/local/sbin/lghs-autologin-apply
install -o root -g "$ADMIN_GROUP" -m 0750 "$ROOT_DIR/updater/lghs-reconcile" /usr/local/sbin/lghs-reconcile
install -o root -g "$ADMIN_GROUP" -m 0750 "$ROOT_DIR/updater/lghs-access-enforce" /usr/local/sbin/lghs-access-enforce
install -o root -g "$ADMIN_GROUP" -m 0750 "$ROOT_DIR/updater/lghs-netqueue" /usr/local/sbin/lghs-netqueue
install -o root -g "$ADMIN_GROUP" -m 0750 "$ROOT_DIR/updater/lghs-install-success-notify" /usr/local/sbin/lghs-install-success-notify
install -o root -g "$ADMIN_GROUP" -m 0750 "$ROOT_DIR/student/lghs-report" /usr/local/sbin/lghs-report
install -o root -g "$ADMIN_GROUP" -m 0750 "$ROOT_DIR/student/lghs-firstboot-provision" /usr/local/sbin/lghs-firstboot-provision
install -o root -g "$ADMIN_GROUP" -m 0750 "$ROOT_DIR/student/lghs-dev-setup" /usr/local/sbin/lghs-dev-setup
install -m 0644 "$ROOT_DIR/bluetooth/lghs_bt_protocol.py" /usr/local/lib/lghs-bt/lghs_bt_protocol.py
install -m 0755 "$ROOT_DIR/bluetooth/lghs-bt-prepare" /usr/local/sbin/lghs-bt-prepare
install -m 0644 "$ROOT_DIR/systemd/lghs-bt-prepare.service" /etc/systemd/system/lghs-bt-prepare.service
install -m 0644 "$ROOT_DIR/systemd/lghs-update.service" /etc/systemd/system/lghs-update.service
install -m 0644 "$ROOT_DIR/systemd/lghs-update.timer" /etc/systemd/system/lghs-update.timer
install -m 0644 "$ROOT_DIR/systemd/lghs-firstboot-provision.service" /etc/systemd/system/lghs-firstboot-provision.service
install -m 0644 "$ROOT_DIR/systemd/lghs-reconcile.service" /etc/systemd/system/lghs-reconcile.service
install -m 0644 "$ROOT_DIR/systemd/lghs-reconcile.timer" /etc/systemd/system/lghs-reconcile.timer
install -m 0644 "$ROOT_DIR/systemd/lghs-netqueue.service" /etc/systemd/system/lghs-netqueue.service
install -m 0644 "$ROOT_DIR/systemd/lghs-netqueue.timer" /etc/systemd/system/lghs-netqueue.timer
install -m 0644 "$ROOT_DIR/systemd/lghs-install-success-notify.service" /etc/systemd/system/lghs-install-success-notify.service
install -d -m 0755 /etc/NetworkManager/dispatcher.d
install -m 0755 "$ROOT_DIR/systemd/90-lghs-netqueue" /etc/NetworkManager/dispatcher.d/90-lghs-netqueue
install -m 0440 "$ROOT_DIR/policies/sudoers/89-lghs-audit" /etc/sudoers.d/89-lghs-audit

touch /var/log/lghs-netqueue.log
chown root:adm /var/log/lghs-netqueue.log 2>/dev/null || true
chmod 0640 /var/log/lghs-netqueue.log

COMMON_PKGS=(git curl python3 openssh-client sudo logrotate libnotify-bin bluez rfkill python3-cryptography network-manager)
if ! command -v flock >/dev/null 2>&1; then COMMON_PKGS+=(util-linux); fi
MISSING_PKGS=()
for pkg in "${COMMON_PKGS[@]}"; do dpkg-query -W -f='${Status}' "$pkg" 2>/dev/null | grep -q 'ok installed' || MISSING_PKGS+=("$pkg"); done
if (( ${#MISSING_PKGS[@]} )); then apt-get update; DEBIAN_FRONTEND=noninteractive apt-get install -y "${MISSING_PKGS[@]}"; fi

if ! id cs_admin >/dev/null 2>&1; then useradd -m -s /bin/bash cs_admin; fi
usermod -aG sudo,"$ADMIN_GROUP" cs_admin
install -d -m 0700 -o cs_admin -g cs_admin /home/cs_admin/.ssh

rm -f /etc/sudoers.d/88-lghs-fleet-admin /etc/sudoers.d/91-lghs-admin /etc/sudoers.d/91-lghs-bootstrap-admin
install -m 0440 "$ROOT_DIR/policies/sudoers/99-lghs-admin" /etc/sudoers.d/99-lghs-admin

if [[ "$ROLE" == "controller" ]]; then
  install -d -m 0755 /usr/local/libexec /usr/local/lib/lghs-python/lghs
  install -m 0644 "$ROOT_DIR/controller/lghs/__init__.py" /usr/local/lib/lghs-python/lghs/__init__.py
  install -m 0644 "$ROOT_DIR/controller/lghs/protocol.py" /usr/local/lib/lghs-python/lghs/protocol.py
  install -m 0644 "$ROOT_DIR/controller/lghs/database.py" /usr/local/lib/lghs-python/lghs/database.py
  install -m 0644 "$ROOT_DIR/controller/lghs/audit.py" /usr/local/lib/lghs-python/lghs/audit.py
  install -m 0644 "$ROOT_DIR/controller/lghs/sudo_state.py" /usr/local/lib/lghs-python/lghs/sudo_state.py
  install -m 0644 "$ROOT_DIR/controller/lghs/health.py" /usr/local/lib/lghs-python/lghs/health.py
  install -m 0644 "$ROOT_DIR/controller/lghs/fleet_ui.py" /usr/local/lib/lghs-python/lghs/fleet_ui.py
  install -m 0644 "$ROOT_DIR/controller/lghs/rollout.py" /usr/local/lib/lghs-python/lghs/rollout.py
  install -m 0644 "$ROOT_DIR/controller/lghs/rollout_manager.py" /usr/local/lib/lghs-python/lghs/rollout_manager.py
  install -m 0644 "$ROOT_DIR/controller/lghs/recovery.py" /usr/local/lib/lghs-python/lghs/recovery.py
  install -m 0644 "$ROOT_DIR/controller/lghs/maintenance.py" /usr/local/lib/lghs-python/lghs/maintenance.py
  install -m 0755 "$ROOT_DIR/controller/lghsctl" /usr/local/libexec/lghsctl-real
  install -m 0755 "$ROOT_DIR/controller/lghsctl-wrapper" /usr/local/sbin/lghsctl
  install -m 0755 "$ROOT_DIR/controller/lghs-console" /usr/local/libexec/lghs-console-legacy
  install -m 0755 "$ROOT_DIR/controller/lghs-console-tunnel" /usr/local/libexec/lghs-console-base
  install -m 0755 "$ROOT_DIR/controller/lghs-console-responsive" /usr/local/libexec/lghs-console-responsive-core
  install -m 0755 "$ROOT_DIR/controller/lghs-console-day2" /usr/local/libexec/lghs-console-day2-core
  install -m 0755 "$ROOT_DIR/controller/lghs-console-day3" /usr/local/libexec/lghs-console-day3-core
  install -m 0755 "$ROOT_DIR/controller/lghs-console-day4" /usr/local/libexec/lghs-console-day4-core
  install -m 0755 "$ROOT_DIR/controller/lghs-console-day5" /usr/local/sbin/lghs-console
  install -m 0755 "$ROOT_DIR/controller/lghs-fleet-command" /usr/local/sbin/lghs-fleet-command
  install -m 0755 "$ROOT_DIR/controller/lghs-fleet-notify" /usr/local/sbin/lghs-fleet-notify
  install -m 0755 "$ROOT_DIR/controller/lghs-fleet-state" /usr/local/sbin/lghs-fleet-state
  install -m 0755 "$ROOT_DIR/controller/lghs-db-migrate" /usr/local/sbin/lghs-db-migrate
  install -m 0755 "$ROOT_DIR/controller/lghs-fleet-rollout" /usr/local/sbin/lghs-fleet-rollout
  install -m 0755 "$ROOT_DIR/controller/lghs-fleet-maintenance" /usr/local/sbin/lghs-fleet-maintenance
  install -m 0755 "$ROOT_DIR/controller/lghs-rollout-manager" /usr/local/sbin/lghs-rollout-manager
  install -m 0755 "$ROOT_DIR/controller/lghs-cloudflare-provision" /usr/local/sbin/lghs-cloudflare-provision
  install -m 0644 "$ROOT_DIR/systemd/lghs-fleet-notify.service" /etc/systemd/system/lghs-fleet-notify.service
  install -m 0755 "$ROOT_DIR/controller/lghs-audit-sync" /usr/local/sbin/lghs-audit-sync
  install -m 0644 "$ROOT_DIR/systemd/lghs-audit-sync.service" /etc/systemd/system/lghs-audit-sync.service
  install -m 0644 "$ROOT_DIR/systemd/lghs-audit-sync.timer" /etc/systemd/system/lghs-audit-sync.timer
  install -m 0755 "$ROOT_DIR/controller/lghs-fleet-api" /usr/local/sbin/lghs-fleet-api
  install -m 0755 "$ROOT_DIR/controller/lghs-fleet-api-cloudflare" /usr/local/sbin/lghs-fleet-api-cloudflare
  install -m 0755 "$ROOT_DIR/controller/lghs-fleet-api-provision" /usr/local/sbin/lghs-fleet-api-provision
  install -m 0644 "$ROOT_DIR/systemd/lghs-fleet-api.service" /etc/systemd/system/lghs-fleet-api.service
  install -m 0644 "$ROOT_DIR/systemd/lghs-rollout-manager.service" /etc/systemd/system/lghs-rollout-manager.service
  install -m 0750 "$ROOT_DIR/controller/lghs-bt-provision" /usr/local/sbin/lghs-bt-provision
  install -m 0644 "$ROOT_DIR/systemd/lghs-bt-provision.service" /etc/systemd/system/lghs-bt-provision.service
  install -m 0755 "$ROOT_DIR/controller/install-remote-admin" /usr/local/sbin/lghs-install-remote-admin

  # Raw RFCOMM sockets are not automatically published in BlueZ SDP. The
  # controller uses the compatibility SDP interface only to advertise the
  # bootstrap serial service; authentication and Wi-Fi encryption remain in
  # the LGHS application protocol.
  install -d -m 0755 /etc/systemd/system/bluetooth.service.d
  cat > /etc/systemd/system/bluetooth.service.d/50-lghs-sdp-compat.conf <<'EOF'
[Service]
ExecStart=
ExecStart=/usr/libexec/bluetooth/bluetoothd --compat
EOF
  chmod 0644 /etc/systemd/system/bluetooth.service.d/50-lghs-sdp-compat.conf

  if [[ ! -f /etc/lghs/fleet.json ]]; then
    printf '%s\n' '{"version":1,"devices":{}}' > /etc/lghs/fleet.json
    chmod 0644 /etc/lghs/fleet.json
  fi

  CTRL_PKGS=(avahi-daemon avahi-utils)
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
  /usr/local/sbin/lghs-db-migrate >/var/lib/lghs/db-migration-last.json
  chmod 0640 /var/lib/lghs/db-migration-last.json

  # The Fleet Web UI is intentionally shelved. Preserve its application/config
  # files for possible future work, but remove all live systemd entrypoints so
  # it consumes no controller resources and cannot reappear after reboot.
  for unit in lghs-fleet-web-cloudflared.service lghs-fleet-web.service lghs-fleet-web-ops.service lghs-fleet-web-cache-sync.path lghs-fleet-web-cache-sync.service; do
    systemctl disable --now "$unit" >/dev/null 2>&1 || true
  done
  rm -f /etc/systemd/system/lghs-fleet-web-cloudflared.service \
        /etc/systemd/system/lghs-fleet-web.service \
        /etc/systemd/system/lghs-fleet-web-ops.service \
        /etc/systemd/system/lghs-fleet-web-cache-sync.path \
        /etc/systemd/system/lghs-fleet-web-cache-sync.service \
        /usr/local/sbin/lghs-fleet-web-cache-sync
  systemctl daemon-reload
  systemctl reset-failed >/dev/null 2>&1 || true

  /bin/bash "$ROOT_DIR/controller/install-remote-admin"
else
  rm -f /etc/systemd/system/bluetooth.service.d/50-lghs-sdp-compat.conf
  getent group lghs-agent >/dev/null 2>&1 || groupadd --system lghs-agent
  if ! id lghs-agent >/dev/null 2>&1; then useradd --system --gid lghs-agent --home-dir /var/lib/lghs-agent --shell /usr/sbin/nologin lghs-agent; fi
  install -d -o lghs-agent -g lghs-agent -m 0700 /var/lib/lghs-agent
  install -d -o root -g root -m 0700 /var/lib/lghs/bootstrap

  install -o root -g "$ADMIN_GROUP" -m 0750 "$ROOT_DIR/student/lghs-enforce" /usr/local/sbin/lghs-enforce
  install -o root -g "$ADMIN_GROUP" -m 0750 "$ROOT_DIR/student/lghs-check" /usr/local/sbin/lghs-check
  install -o root -g root -m 0755 "$ROOT_DIR/student/lghs-agent" /usr/local/sbin/lghs-agent
  if [[ -f "$ROOT_DIR/updater/patch-agent-status-guard.py" ]]; then
    python3 "$ROOT_DIR/updater/patch-agent-status-guard.py" /usr/local/sbin/lghs-agent
  fi
  install -o root -g root -m 0750 "$ROOT_DIR/student/lghs-command-executor" /usr/local/sbin/lghs-command-executor
  install -o root -g root -m 0755 "$ROOT_DIR/student/lghs-discovery-advertise" /usr/local/sbin/lghs-discovery-advertise
  install -o root -g root -m 0750 "$ROOT_DIR/student/lghs-bt-bootstrap" /usr/local/sbin/lghs-bt-bootstrap
  install -o root -g "$ADMIN_GROUP" -m 0750 "$ROOT_DIR/student/lghs-network-ui-apply" /usr/local/sbin/lghs-network-ui-apply
  install -o root -g "$ADMIN_GROUP" -m 0750 "$ROOT_DIR/student/lghs-install-network-ui" /usr/local/sbin/lghs-install-network-ui
  install -o root -g "$ADMIN_GROUP" -m 0750 "$ROOT_DIR/student/lghs-sudo-broker" /usr/local/sbin/lghs-sudo-broker
  install -o root -g "$ADMIN_GROUP" -m 0750 "$ROOT_DIR/student/lghs-approved-exec" /usr/local/sbin/lghs-approved-exec
  install -o root -g "$ADMIN_GROUP" -m 0750 "$ROOT_DIR/student/lghs-local-exec" /usr/local/sbin/lghs-local-exec
  install -o root -g "$ADMIN_GROUP" -m 0750 "$ROOT_DIR/student/lghs-sudo-admin" /usr/local/sbin/lghs-sudo-admin
  install -o root -g "$ADMIN_GROUP" -m 0750 "$ROOT_DIR/student/lghs-sudo-selftest" /usr/local/sbin/lghs-sudo-selftest
  install -o root -g "$ADMIN_GROUP" -m 0750 "$ROOT_DIR/student/lghs-audit-export" /usr/local/sbin/lghs-audit-export
  install -o root -g "$ADMIN_GROUP" -m 0750 "$ROOT_DIR/student/lghs-cloudflare-install" /usr/local/sbin/lghs-cloudflare-install
  install -o root -g "$ADMIN_GROUP" -m 0750 "$ROOT_DIR/student/lghs-telemetry-configure" /usr/local/sbin/lghs-telemetry-configure
  install -o root -g "$ADMIN_GROUP" -m 0750 "$ROOT_DIR/student/lghs-telemetry-push" /usr/local/sbin/lghs-telemetry-push
  install -m 0644 "$ROOT_DIR/systemd/lghs-telemetry-push.service" /etc/systemd/system/lghs-telemetry-push.service
  install -m 0644 "$ROOT_DIR/systemd/lghs-agent.service" /etc/systemd/system/lghs-agent.service
  install -m 0644 "$ROOT_DIR/systemd/lghs-command-executor.service" /etc/systemd/system/lghs-command-executor.service
  install -m 0644 "$ROOT_DIR/systemd/lghs-discovery-advertise.service" /etc/systemd/system/lghs-discovery-advertise.service
  install -m 0644 "$ROOT_DIR/systemd/lghs-bt-bootstrap.service" /etc/systemd/system/lghs-bt-bootstrap.service
  install -m 0755 "$ROOT_DIR/student/sudo" /usr/local/bin/sudo
  install -d -m 0700 /var/lib/lghs/sudo-requests
  touch /var/log/lghs-sudo-audit.jsonl /var/log/sudo.log /var/log/lghs-update.log /var/log/lghs-os-update.log
  chown root:adm /var/log/lghs-sudo-audit.jsonl /var/log/sudo.log /var/log/lghs-update.log /var/log/lghs-os-update.log 2>/dev/null || true
  chmod 0640 /var/log/lghs-sudo-audit.jsonl /var/log/sudo.log /var/log/lghs-update.log /var/log/lghs-os-update.log

  install -m 0440 "$ROOT_DIR/policies/sudoers/90-lghs-student" /etc/sudoers.d/90-lghs-student
  install -m 0644 "$ROOT_DIR/policies/polkit/49-lghs-network.rules" /etc/polkit-1/rules.d/49-lghs-network.rules

  STUDENT_PKGS=(openssh-server network-manager polkitd avahi-daemon avahi-utils)
  MISSING_PKGS=()
  for pkg in "${STUDENT_PKGS[@]}"; do dpkg-query -W -f='${Status}' "$pkg" 2>/dev/null | grep -q 'ok installed' || MISSING_PKGS+=("$pkg"); done
  if (( ${#MISSING_PKGS[@]} )); then apt-get update; DEBIAN_FRONTEND=noninteractive apt-get install -y "${MISSING_PKGS[@]}"; fi

  if [[ -f /etc/lghs/controller_ed25519.pub ]]; then install -m 0600 -o cs_admin -g cs_admin /etc/lghs/controller_ed25519.pub /home/cs_admin/.ssh/authorized_keys; fi

  install -d -m 0755 /etc/ssh/sshd_config.d
  cat > /etc/ssh/sshd_config.d/90-lghs-fleet.conf <<'EOF'
Match User cs_admin
    PasswordAuthentication yes
    KbdInteractiveAuthentication yes
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

  if [[ -s /etc/lghs/secrets/fleet-api-token ]]; then install -o lghs-agent -g lghs-agent -m 0400 /etc/lghs/secrets/fleet-api-token /var/lib/lghs-agent/fleet-api-token; fi
  if [[ -s /etc/lghs/fleet-api.conf ]]; then install -o lghs-agent -g lghs-agent -m 0400 /etc/lghs/fleet-api.conf /var/lib/lghs-agent/fleet-api.conf; fi
  printf '%s\n' "$(cat "$ROOT_DIR/VERSION")" > /var/lib/lghs-agent/version
  chown lghs-agent:lghs-agent /var/lib/lghs-agent/version; chmod 0400 /var/lib/lghs-agent/version

  if [[ "${LGHS_IMAGE_BUILD:-0}" == "1" ]]; then
    install -m 0600 /dev/null /etc/lghs/bluetooth-bootstrap-enabled
  fi

  if [[ ! -f /usr/local/lib/lghs/libnetman.so.hardened ]]; then /usr/local/sbin/lghs-install-network-ui; else /usr/local/sbin/lghs-network-ui-apply; fi
fi

/usr/local/sbin/lghs-dev-setup
/usr/local/sbin/lghs-autologin-apply || true
visudo -cf /etc/sudoers >/dev/null
systemctl daemon-reload
systemctl enable lghs-update.service lghs-firstboot-provision.service
systemctl enable --now avahi-daemon.service bluetooth.service
if [[ "$ROLE" == "controller" ]]; then
  # Apply the persistent bluetoothd --compat override now, not only after the
  # next reboot, so the provisioning service can publish its SDP record.
  systemctl restart bluetooth.service
fi
systemctl enable lghs-bt-prepare.service
systemctl reset-failed lghs-bt-prepare.service >/dev/null 2>&1 || true
systemctl restart lghs-bt-prepare.service
systemctl enable --now lghs-update.timer lghs-reconcile.timer lghs-netqueue.timer
if [[ "$ROLE" == "student" ]]; then
  systemctl disable --now lghs-telemetry-push.service >/dev/null 2>&1 || true
  systemctl enable --now lghs-policy.service lghs-command-executor.service lghs-agent.service lghs-discovery-advertise.service ssh.service
  systemctl enable lghs-bt-bootstrap.service
  systemctl reset-failed lghs-bt-bootstrap.service >/dev/null 2>&1 || true
  if [[ -f /etc/lghs/bluetooth-bootstrap-enabled && ! -f /var/lib/lghs/bootstrap/wifi-provisioned.json ]]; then
    systemctl start lghs-bt-bootstrap.service || true
  fi
  systemctl restart lghs-policy.service lghs-command-executor.service lghs-agent.service
  systemctl try-restart ssh.service >/dev/null 2>&1 || true
else
  systemctl enable --now lghs-audit-sync.timer lghs-fleet-notify.service lghs-fleet-api.service lghs-rollout-manager.service lghs-bt-provision.service
  systemctl reset-failed lghs-bt-provision.service lghs-rollout-manager.service >/dev/null 2>&1 || true
  systemctl try-restart lghs-fleet-notify.service
  systemctl try-restart lghs-fleet-api.service
  systemctl try-restart lghs-rollout-manager.service
  systemctl try-restart lghs-bt-provision.service
fi
systemctl enable lghs-install-success-notify.service
systemctl start --no-block lghs-install-success-notify.service >/dev/null 2>&1 || true
/usr/local/sbin/lghs-access-enforce
if systemctl is-system-running --quiet 2>/dev/null || systemctl is-system-running 2>/dev/null | grep -Eq 'running|degraded'; then
  systemctl try-restart avahi-daemon.service || true
  systemctl start --no-block lghs-netqueue.service >/dev/null 2>&1 || true
fi

echo "LGHS $ROLE installation completed."
