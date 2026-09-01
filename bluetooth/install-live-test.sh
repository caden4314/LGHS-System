#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
START=0
REARM=0

usage() {
  cat <<'EOF'
Usage: sudo ./bluetooth/install-live-test.sh [--start] [--rearm]

Installs only the LGHS Bluetooth/Cloudflare zero-touch test surface from this
checkout. The installed role is read from /etc/lghs/role.

  --start   Start/restart the applicable Bluetooth provisioning service.
  --rearm   Student only: explicitly back up and remove the existing
            wifi-provisioned marker, then start Bluetooth provisioning again.
            This can re-apply Wi-Fi and the device Cloudflare tunnel.
EOF
}

while (($#)); do
  case "$1" in
    --start) START=1 ;;
    --rearm) START=1; REARM=1 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
  shift
done

if [[ $EUID -ne 0 ]]; then
  echo "Run with sudo." >&2
  exit 1
fi

if [[ ! -f /etc/lghs/role ]]; then
  echo "Missing /etc/lghs/role; this does not look like an installed LGHS system." >&2
  exit 1
fi

ROLE="$(tr -d '[:space:]' < /etc/lghs/role)"
if [[ "$ROLE" != controller && "$ROLE" != student ]]; then
  echo "Unsupported LGHS role: $ROLE" >&2
  exit 1
fi

install -d -m 0755 /usr/local/lib/lghs-bt
install -m 0644 "$ROOT_DIR/bluetooth/lghs_bt_protocol.py" /usr/local/lib/lghs-bt/lghs_bt_protocol.py
install -m 0755 "$ROOT_DIR/bluetooth/lghs-bt-prepare" /usr/local/sbin/lghs-bt-prepare
install -m 0644 "$ROOT_DIR/systemd/lghs-bt-prepare.service" /etc/systemd/system/lghs-bt-prepare.service

if [[ "$ROLE" == controller ]]; then
  install -m 0750 "$ROOT_DIR/controller/lghs-bt-provision" /usr/local/sbin/lghs-bt-provision
  install -m 0755 "$ROOT_DIR/controller/lghs-cloudflare-provision" /usr/local/sbin/lghs-cloudflare-provision
  install -m 0755 "$ROOT_DIR/controller/lghs-cloudflare-token-check" /usr/local/sbin/lghs-cloudflare-token-check
  install -m 0644 "$ROOT_DIR/systemd/lghs-bt-provision.service" /etc/systemd/system/lghs-bt-provision.service

  install -d -m 0755 /etc/systemd/system/bluetooth.service.d
  cat > /etc/systemd/system/bluetooth.service.d/50-lghs-sdp-compat.conf <<'EOF'
[Service]
ExecStart=
ExecStart=/usr/libexec/bluetooth/bluetoothd --compat
EOF
  chmod 0644 /etc/systemd/system/bluetooth.service.d/50-lghs-sdp-compat.conf

  systemctl daemon-reload
  systemctl enable lghs-bt-prepare.service lghs-bt-provision.service >/dev/null

  echo "Installed controller Bluetooth zero-touch test files."
  /usr/local/sbin/lghs-cloudflare-token-check || true

  if (( START )); then
    systemctl restart bluetooth.service
    systemctl restart lghs-bt-prepare.service
    systemctl restart lghs-bt-provision.service
    echo "Controller Bluetooth provisioning started."
  else
    echo "Not started. Re-run with --start when ready to advertise/provision."
  fi
else
  install -m 0750 "$ROOT_DIR/student/lghs-bt-bootstrap" /usr/local/sbin/lghs-bt-bootstrap
  install -m 0750 "$ROOT_DIR/student/lghs-cloudflare-install" /usr/local/sbin/lghs-cloudflare-install
  install -m 0750 "$ROOT_DIR/student/lghs-firstboot-provision" /usr/local/sbin/lghs-firstboot-provision
  install -m 0644 "$ROOT_DIR/systemd/lghs-bt-bootstrap.service" /etc/systemd/system/lghs-bt-bootstrap.service
  install -m 0644 "$ROOT_DIR/systemd/lghs-firstboot-provision.service" /etc/systemd/system/lghs-firstboot-provision.service

  install -d -m 0700 /var/lib/lghs/bootstrap
  touch /etc/lghs/bluetooth-bootstrap-enabled
  chmod 0644 /etc/lghs/bluetooth-bootstrap-enabled

  systemctl daemon-reload
  systemctl enable lghs-bt-prepare.service lghs-bt-bootstrap.service >/dev/null

  token_ok=0
  for f in /etc/lghs/secrets/fleet-api-token /var/lib/lghs-agent/fleet-api-token; do
    if [[ -s "$f" ]]; then token_ok=1; break; fi
  done
  if (( ! token_ok )); then
    echo "WARNING: no Fleet API token is currently installed; BT mutual authentication cannot start yet." >&2
  fi

  if (( REARM )); then
    marker=/var/lib/lghs/bootstrap/wifi-provisioned.json
    if [[ -e "$marker" ]]; then
      stamp="$(date -u +%Y%m%dT%H%M%SZ)"
      backup="${marker}.pre-live-test-${stamp}"
      cp -a "$marker" "$backup"
      rm -f "$marker"
      echo "Backed up prior Wi-Fi provision marker to $backup"
    fi
  fi

  echo "Installed student Bluetooth zero-touch test files."
  if (( START )); then
    if [[ -e /var/lib/lghs/bootstrap/wifi-provisioned.json ]]; then
      echo "Existing Wi-Fi provisioning marker is present; service intentionally not restarted."
      echo "Use --rearm only when you intentionally want CS-999 to repeat the BT provisioning flow."
      exit 3
    fi
    systemctl restart bluetooth.service
    systemctl restart lghs-bt-prepare.service
    systemctl restart lghs-bt-bootstrap.service
    echo "Student Bluetooth bootstrap started."
  else
    echo "Not started. Use --start for an unprovisioned device or --rearm for the existing test Pi."
  fi
fi

printf '\n=== LGHS BT TEST STATUS ===\n'
systemctl --no-pager --full status lghs-bt-prepare.service 2>/dev/null | sed -n '1,12p' || true
if [[ "$ROLE" == controller ]]; then
  systemctl --no-pager --full status lghs-bt-provision.service 2>/dev/null | sed -n '1,14p' || true
else
  systemctl --no-pager --full status lghs-bt-bootstrap.service 2>/dev/null | sed -n '1,14p' || true
fi
