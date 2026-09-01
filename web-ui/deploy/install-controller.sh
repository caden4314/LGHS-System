#!/usr/bin/env bash
set -euo pipefail

[[ $EUID -eq 0 ]] || { echo "Run as root" >&2; exit 1; }

SOURCE_DIR="${1:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
DIST="$SOURCE_DIR/dist"
GATEWAY="$SOURCE_DIR/gateway"
SERVICE="$SOURCE_DIR/deploy/lghs-fleet-web.service"
OPS_SERVICE="$SOURCE_DIR/deploy/lghs-fleet-web-ops.service"
OPS="$SOURCE_DIR/ops/lghs-web-ops"
INSTALL_ROOT=/opt/lghs-fleet-web
STATIC_ROOT=/usr/local/share/lghs-web-ui
CONFIG_ROOT=/etc/lghs-web
STATE_ROOT=/var/lib/lghs-web
TOKEN_SOURCE=/etc/lghs/fleet-api-tokens.json
TOKEN_TARGET=$CONFIG_ROOT/fleet-admin-token.json
ROLE_FILE=$CONFIG_ROOT/roles.json
CSRF_FILE=$CONFIG_ROOT/csrf.key
ENV_FILE=/etc/lghs/fleet-web.env

[[ -f "$DIST/index.html" ]] || { echo "Missing production frontend build at $DIST/index.html" >&2; exit 2; }
[[ -f "$GATEWAY/app.py" && -f "$GATEWAY/requirements.txt" ]] || { echo "Missing Fleet web gateway sources" >&2; exit 2; }
[[ -f "$SERVICE" && -f "$OPS_SERVICE" && -f "$OPS" ]] || { echo "Missing Fleet web service/broker sources" >&2; exit 2; }
[[ -f "$TOKEN_SOURCE" ]] || { echo "Fleet API token registry not found: $TOKEN_SOURCE" >&2; exit 2; }

getent group lghs-web >/dev/null 2>&1 || groupadd --system lghs-web
if ! id lghs-web >/dev/null 2>&1; then
  useradd --system --gid lghs-web --no-create-home --home-dir /nonexistent --shell /usr/sbin/nologin lghs-web
fi

install -d -m 0755 -o root -g root "$INSTALL_ROOT" "$STATIC_ROOT"
install -d -m 0750 -o root -g lghs-web "$CONFIG_ROOT" "$STATE_ROOT"
install -m 0644 -o root -g root "$GATEWAY/app.py" "$INSTALL_ROOT/app.py"
install -m 0644 -o root -g root "$GATEWAY/requirements.txt" "$INSTALL_ROOT/requirements.txt"
install -m 0755 -o root -g root "$OPS" /usr/local/libexec/lghs-web-ops

rm -rf "$STATIC_ROOT"/*
cp -a "$DIST"/. "$STATIC_ROOT"/
chown -R root:root "$STATIC_ROOT"
find "$STATIC_ROOT" -type d -exec chmod 0755 {} +
find "$STATIC_ROOT" -type f -exec chmod 0644 {} +

if [[ ! -x "$INSTALL_ROOT/venv/bin/python" ]]; then
  python3 -m venv "$INSTALL_ROOT/venv"
fi
"$INSTALL_ROOT/venv/bin/python" -m pip install --disable-pip-version-check --no-input --requirement "$INSTALL_ROOT/requirements.txt"

python3 - "$TOKEN_SOURCE" "$TOKEN_TARGET" <<'PY'
import json, os, sys, tempfile, pwd, grp
from pathlib import Path
source, target = map(Path, sys.argv[1:3])
data = json.loads(source.read_text(encoding='utf-8'))
token = str(data.get('admin_token') or '') if isinstance(data, dict) else ''
if len(token) < 32:
    raise SystemExit('Fleet API admin token is missing or invalid')
target.parent.mkdir(parents=True, exist_ok=True)
fd, name = tempfile.mkstemp(prefix=target.name + '.', dir=str(target.parent))
try:
    with os.fdopen(fd, 'w', encoding='utf-8') as handle:
        json.dump({'admin_token': token}, handle, separators=(',', ':'))
        handle.write('\n')
    os.chmod(name, 0o400)
    os.chown(name, pwd.getpwnam('lghs-web').pw_uid, grp.getgrnam('lghs-web').gr_gid)
    os.replace(name, target)
finally:
    try: os.unlink(name)
    except FileNotFoundError: pass
PY

# Migrate the old preview paths if present, without making /etc/lghs broadly
# readable by the web service account.
if [[ ! -f "$ROLE_FILE" ]]; then
  if [[ -f /etc/lghs/web-roles.json ]]; then
    install -m 0440 -o root -g lghs-web /etc/lghs/web-roles.json "$ROLE_FILE"
  else
    printf '{"version":1,"users":{}}\n' > "$ROLE_FILE"
    chown root:lghs-web "$ROLE_FILE"
    chmod 0440 "$ROLE_FILE"
  fi
fi

if [[ ! -f "$CSRF_FILE" ]]; then
  if [[ -f /etc/lghs/web-csrf.key ]]; then
    install -m 0400 -o lghs-web -g lghs-web /etc/lghs/web-csrf.key "$CSRF_FILE"
  else
    python3 - <<'PY' > "$CSRF_FILE"
import secrets
print(secrets.token_hex(32))
PY
    chown lghs-web:lghs-web "$CSRF_FILE"
    chmod 0400 "$CSRF_FILE"
  fi
fi

if [[ ! -f "$ENV_FILE" ]]; then
  cat > "$ENV_FILE" <<'EOF'
LGHS_WEB_FLEET_API=http://127.0.0.1:8789
LGHS_WEB_PUBLIC_ORIGIN=https://fleet.scenicrouteservers.com
LGHS_WEB_CF_TEAM_DOMAIN=https://CHANGE-ME.cloudflareaccess.com
LGHS_WEB_CF_AUDIENCE=CHANGE-ME
LGHS_WEB_ALLOWED_HOSTS=fleet.scenicrouteservers.com,127.0.0.1,localhost
EOF
fi
chown root:root "$ENV_FILE"
chmod 0600 "$ENV_FILE"

install -m 0644 -o root -g root "$SERVICE" /etc/systemd/system/lghs-fleet-web.service
install -m 0644 -o root -g root "$OPS_SERVICE" /etc/systemd/system/lghs-fleet-web-ops.service
systemctl daemon-reload
systemctl enable lghs-fleet-web-ops.service lghs-fleet-web.service >/dev/null
systemctl restart lghs-fleet-web-ops.service

if grep -q 'CHANGE-ME' "$ENV_FILE"; then
  echo "Fleet web backend installed, but Cloudflare Access values are not configured yet."
  echo "Edit $ENV_FILE and $ROLE_FILE before starting lghs-fleet-web.service."
  exit 0
fi

systemctl restart lghs-fleet-web.service
systemctl --no-pager --full status lghs-fleet-web-ops.service
systemctl --no-pager --full status lghs-fleet-web.service
