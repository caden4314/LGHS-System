#!/usr/bin/env bash
set -euo pipefail

REPO_URL="${LGHS_REPO_URL:-https://github.com/caden4314/LGHS-System.git}"
BRANCH="${LGHS_UPDATE_BRANCH:-main}"
SOURCE=/opt/lghs/stock-source
APPLY=/opt/lghs/stock-apply
BUILD_BIN=/usr/local/lib/lghs-stock-bootstrap-bin
SMUDGE=/usr/local/libexec/lghs-user-map-smudge
CLEAN=/usr/local/libexec/lghs-user-map-clean

log(){ printf '[LGHS stock] %s\n' "$*"; }
die(){ echo "LGHS stock bootstrap: $*" >&2; exit 1; }
[[ $EUID -eq 0 ]] || die "Run with sudo"

DEVICE="$(hostname -s | tr '[:lower:]' '[:upper:]')"
[[ "$DEVICE" =~ ^CS-[0-9]{1,3}$ ]] || die "Hostname must be CS-## (current: $DEVICE)"
EXPECTED_STUDENT="$(printf '%s' "$DEVICE" | tr '[:upper:]' '[:lower:]')"
STUDENT_USER="${LGHS_STUDENT_USER:-${SUDO_USER:-}}"
[[ -n "$STUDENT_USER" && "$STUDENT_USER" != root ]] || STUDENT_USER="$EXPECTED_STUDENT"
[[ "$STUDENT_USER" == "$EXPECTED_STUDENT" ]] || die "Student account must match hostname: expected $EXPECTED_STUDENT, got $STUDENT_USER"
id "$STUDENT_USER" >/dev/null 2>&1 || die "Student account does not exist: $STUDENT_USER"
ADMIN_USER="${LGHS_ADMIN_USER:-cs-admin}"
[[ "$ADMIN_USER" =~ ^[a-z_][a-z0-9_-]*$ ]] || die "Invalid admin account: $ADMIN_USER"

log "Device: $DEVICE"
log "Student: $STUDENT_USER"
log "Admin: $ADMIN_USER"
log "Installing stock-OS bootstrap prerequisites..."
apt-get update
DEBIAN_FRONTEND=noninteractive apt-get install -y \
  git curl ca-certificates openssh-server sudo bluez rfkill network-manager \
  python3 python3-cryptography avahi-daemon avahi-utils

install -d -m 0755 /opt/lghs /etc/lghs /usr/local/lib/lghs-bt /usr/local/libexec
install -d -m 0700 /etc/lghs/secrets /var/lib/lghs/bootstrap /etc/ssh/authorized_keys
printf '%s\n' student > /etc/lghs/role
printf '%s\n' "$STUDENT_USER" > /etc/lghs/student-user
printf '%s\n' "$ADMIN_USER" > /etc/lghs/admin-user
chmod 0644 /etc/lghs/role /etc/lghs/student-user /etc/lghs/admin-user
cat > /etc/lghs/device.conf <<EOF
DEVICE_ID=$DEVICE
ROLE=student
HOSTNAME=$DEVICE
BOARD=Raspberry Pi 5
ARCH=arm64
DEPLOYMENT=stock-bootstrap
EOF
chmod 0644 /etc/lghs/device.conf

if ! id "$ADMIN_USER" >/dev/null 2>&1; then
  useradd -m -s /bin/bash "$ADMIN_USER"
fi
usermod -aG sudo "$ADMIN_USER"

if [[ "${LGHS_NONINTERACTIVE:-0}" != 1 ]]; then
  echo
  echo "Set the teacher password for $ADMIN_USER (Root will use the same password)."
  while :; do
    read -rsp "Teacher password: " ADMIN_PASS; echo
    read -rsp "Confirm password: " ADMIN_PASS2; echo
    [[ -n "$ADMIN_PASS" ]] || { echo "Password cannot be empty."; continue; }
    [[ "$ADMIN_PASS" == "$ADMIN_PASS2" ]] || { echo "Passwords did not match."; continue; }
    break
  done
  printf '%s:%s\n' "$ADMIN_USER" "$ADMIN_PASS" | chpasswd
  printf 'root:%s\n' "$ADMIN_PASS" | chpasswd
  unset ADMIN_PASS ADMIN_PASS2
else
  [[ -n "${LGHS_ADMIN_PASSWORD:-}" ]] || die "LGHS_ADMIN_PASSWORD is required with LGHS_NONINTERACTIVE=1"
  printf '%s:%s\n' "$ADMIN_USER" "$LGHS_ADMIN_PASSWORD" | chpasswd
  printf 'root:%s\n' "$LGHS_ADMIN_PASSWORD" | chpasswd
  unset LGHS_ADMIN_PASSWORD
fi

if [[ ! -d "$SOURCE/.git" ]]; then
  rm -rf "$SOURCE"
  git clone --branch "$BRANCH" "$REPO_URL" "$SOURCE"
else
  git -C "$SOURCE" remote set-url origin "$REPO_URL"
  git -C "$SOURCE" fetch --prune origin "$BRANCH"
  git -C "$SOURCE" reset --hard "origin/$BRANCH"
fi
COMMIT="$(git -C "$SOURCE" rev-parse HEAD)"
log "LGHS source: ${COMMIT:0:12}"

# Persist the stock account mapping in Git's checkout filters. LGHS's upstream
# source intentionally keeps the legacy image account names for compatibility;
# on this device every future git reset performed by lghs-update is smudged to
# cs-##/cs-admin while the clean filter maps it back for Git comparisons. This
# keeps the updater checkout clean and prevents a future update from reverting
# the stock device to lg_cs_cont/cs_admin.
cat > "$SMUDGE" <<'PY'
#!/usr/bin/env python3
import sys
from pathlib import Path
raw = sys.stdin.buffer.read()
try:
    text = raw.decode('utf-8')
except UnicodeDecodeError:
    sys.stdout.buffer.write(raw); raise SystemExit(0)
student = Path('/etc/lghs/student-user').read_text(encoding='utf-8').strip()
admin = Path('/etc/lghs/admin-user').read_text(encoding='utf-8').strip()
sys.stdout.write(text.replace('lg_cs_cont', student).replace('cs_admin', admin))
PY
cat > "$CLEAN" <<'PY'
#!/usr/bin/env python3
import sys
from pathlib import Path
raw = sys.stdin.buffer.read()
try:
    text = raw.decode('utf-8')
except UnicodeDecodeError:
    sys.stdout.buffer.write(raw); raise SystemExit(0)
student = Path('/etc/lghs/student-user').read_text(encoding='utf-8').strip()
admin = Path('/etc/lghs/admin-user').read_text(encoding='utf-8').strip()
sys.stdout.write(text.replace(student, 'lg_cs_cont').replace(admin, 'cs_admin'))
PY
chmod 0755 "$SMUDGE" "$CLEAN"
git -C "$SOURCE" config filter.lghs-user-map.smudge "$SMUDGE"
git -C "$SOURCE" config filter.lghs-user-map.clean "$CLEAN"
git -C "$SOURCE" config filter.lghs-user-map.required true
install -d -m 0755 "$SOURCE/.git/info"
printf '* filter=lghs-user-map\n' > "$SOURCE/.git/info/attributes"
git -C "$SOURCE" reset --hard HEAD >/dev/null

cat > /etc/lghs/update.env <<EOF
LGHS_REPO_URL=$REPO_URL
LGHS_UPDATE_BRANCH=$BRANCH
LGHS_UPDATE_CHECKOUT=$SOURCE
EOF
chmod 0644 /etc/lghs/update.env

# Build a disposable device-local tree for the initial install. This is also a
# defense-in-depth mapping in case a Git implementation skipped a filter on a
# file type; installed scripts/policies must never reference the wrong account.
rm -rf "$APPLY"
cp -a "$SOURCE" "$APPLY"
python3 - "$APPLY" "$STUDENT_USER" "$ADMIN_USER" <<'PY'
import sys
from pathlib import Path
root = Path(sys.argv[1]); student = sys.argv[2]; admin = sys.argv[3]
for path in root.rglob('*'):
    if not path.is_file() or '.git' in path.parts:
        continue
    try:
        raw = path.read_bytes(); text = raw.decode('utf-8')
    except Exception:
        continue
    mapped = text.replace('lg_cs_cont', student).replace('cs_admin', admin)
    if mapped != text:
        path.write_text(mapped, encoding='utf-8')
PY
printf '%s\n' "$COMMIT" > "$APPLY/.lghs-source-commit"

# Run the normal installer while deliberately suppressing live service starts.
# This installs the complete LGHS payload, but Fleet remains dormant until the
# Bluetooth -> Cloudflare -> controller verification sequence succeeds.
install -d -m 0755 "$BUILD_BIN"
cat > "$BUILD_BIN/systemctl" <<'EOS'
#!/bin/bash
set -e
REAL=/usr/bin/systemctl
cmd="${1:-}"; shift || true
case "$cmd" in
  enable|disable)
    filtered=()
    for arg in "$@"; do [[ "$arg" == --now ]] || filtered+=("$arg"); done
    exec "$REAL" "$cmd" "${filtered[@]}"
    ;;
  start|restart|try-restart|reset-failed|daemon-reload) exit 0 ;;
  is-system-running) echo offline; exit 1 ;;
  *) exec "$REAL" "$cmd" "$@" ;;
esac
EOS
chmod 0755 "$BUILD_BIN/systemctl"
trap 'rm -rf "$BUILD_BIN"' EXIT
PATH="$BUILD_BIN:$PATH" /bin/bash "$APPLY/install.sh" student
rm -rf "$BUILD_BIN"
trap - EXIT

# The stock account remains usable for recovery until provisioning succeeds.
# No Fleet service is allowed to run before Cloudflare has been controller-
# verified and a per-device Fleet credential has been delivered.
systemctl disable --now \
  lghs-agent.service lghs-command-executor.service lghs-discovery-advertise.service \
  lghs-policy.service lghs-update.timer lghs-reconcile.timer lghs-netqueue.timer \
  >/dev/null 2>&1 || true

# Controller SSH authorization is delivered over the authenticated Bluetooth
# channel and lives outside the user's home so the hardened BT service need not
# write arbitrary home-directory content.
cat > /etc/ssh/sshd_config.d/91-lghs-stock-admin.conf <<EOF
Match User $ADMIN_USER
    PubkeyAuthentication yes
    PasswordAuthentication yes
    KbdInteractiveAuthentication yes
    AuthorizedKeysFile .ssh/authorized_keys /etc/ssh/authorized_keys/%u
    X11Forwarding no
    AllowAgentForwarding no
    AllowTcpForwarding no
    PermitTunnel no
    GatewayPorts no
EOF
chmod 0644 /etc/ssh/sshd_config.d/91-lghs-stock-admin.conf
ssh-keygen -A
sshd -t
systemctl enable --now ssh.service bluetooth.service NetworkManager.service

# A one-time credential authenticates first Bluetooth contact. It is not the
# Fleet token and is deleted after Fleet enrollment completes.
BOOT_TOKEN=/etc/lghs/secrets/bootstrap-token
if [[ ! -s "$BOOT_TOKEN" ]]; then
  python3 - <<'PY' > "$BOOT_TOKEN"
import secrets
print(secrets.token_urlsafe(48))
PY
  chmod 0600 "$BOOT_TOKEN"
fi
install -m 0600 /dev/null /etc/lghs/bluetooth-bootstrap-enabled

# Ensure the stock bootstrap uses the updated unit/script from this checkout.
install -m 0644 "$APPLY/bluetooth/lghs_bt_protocol.py" /usr/local/lib/lghs-bt/lghs_bt_protocol.py
install -m 0755 "$APPLY/bluetooth/lghs-bt-prepare" /usr/local/sbin/lghs-bt-prepare
install -m 0755 "$APPLY/student/lghs-bt-bootstrap" /usr/local/sbin/lghs-bt-bootstrap
install -m 0755 "$APPLY/student/lghs-cloudflare-install" /usr/local/sbin/lghs-cloudflare-install
install -m 0644 "$APPLY/systemd/lghs-bt-prepare.service" /etc/systemd/system/lghs-bt-prepare.service
install -m 0644 "$APPLY/systemd/lghs-bt-bootstrap.service" /etc/systemd/system/lghs-bt-bootstrap.service
systemctl daemon-reload
systemctl enable --now lghs-bt-prepare.service
systemctl enable --now lghs-bt-bootstrap.service

printf '%s\n' "$COMMIT" > /etc/lghs/source-commit
printf '%s\n' "$COMMIT" > /var/lib/lghs/update/current-commit

TOKEN="$(cat "$BOOT_TOKEN")"
echo
echo "============================================================"
echo " LGHS STOCK BOOTSTRAP READY: $DEVICE"
echo "============================================================"
echo "Bluetooth is waiting for LGCSCONT."
echo
echo "1) On your Windows manager, update LGCSCONT first:"
echo '  ssh LGCSCONT-CF "sudo env LGHS_UPDATE_BRANCH=main /usr/local/sbin/lghs-update"'
echo '  ssh LGCSCONT-CF "sudo systemctl restart lghs-bt-provision.service"'
echo
echo "2) Then register this ONE-TIME Bluetooth credential in Windows PowerShell:"
echo "  \$bt = '$TOKEN'"
echo "  \$bt | ssh LGCSCONT-CF \"sudo python3 /opt/lghs/repo/controller/lghs-bootstrap-enroll $DEVICE\""
echo '  Remove-Variable bt'
echo
echo "3) Watch the controller complete Bluetooth -> Cloudflare verify -> Fleet:"
echo '  ssh LGCSCONT-CF "sudo journalctl -fu lghs-bt-provision.service"'
echo
echo "After Cloudflare is verified, the controller creates and delivers the Fleet token automatically."
echo "Do NOT run lghs-imager-enroll or manually create a Fleet token for this stock deployment."
