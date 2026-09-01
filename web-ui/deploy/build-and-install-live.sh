#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [[ $EUID -eq 0 ]]; then
  echo "Run this helper as the normal controller admin user, not root." >&2
  echo "It will use sudo only for the final system installation." >&2
  exit 1
fi

command -v node >/dev/null 2>&1 || { echo "node is required on LGCSCONT" >&2; exit 2; }
command -v npm >/dev/null 2>&1 || { echo "npm is required on LGCSCONT" >&2; exit 2; }
command -v sudo >/dev/null 2>&1 || { echo "sudo is required" >&2; exit 2; }

NODE_VERSION="$(node -p 'process.versions.node')"
node - <<'NODE'
const [maj,min] = process.versions.node.split('.').map(Number)
const ok = (maj > 22) || (maj === 22 && min >= 12) || (maj === 20 && min >= 19)
if (!ok) {
  console.error(`Node ${process.versions.node} is too old. Need Node 20.19+, 22.12+, or newer.`)
  process.exit(1)
}
NODE

echo "Building LGHS Fleet Web UI with Node $NODE_VERSION"
cd "$ROOT_DIR"
npm install --no-audit --no-fund
npm run build

test -f dist/index.html

echo
echo "Installing production bundle on LGCSCONT..."
sudo bash "$ROOT_DIR/deploy/install-controller.sh" "$ROOT_DIR"

echo
echo "=== INSTALL RESULT ==="
echo "Frontend: $ROOT_DIR/dist"
echo "Service:  lghs-fleet-web.service"
echo "Origin:   http://127.0.0.1:8790"
echo
if grep -q 'CHANGE-ME' /etc/lghs/fleet-web.env 2>/dev/null; then
  echo "Cloudflare Access values still need to be configured in /etc/lghs/fleet-web.env."
  echo "The service is installed/enabled but intentionally not started yet."
else
  systemctl --no-pager --full status lghs-fleet-web.service || true
  curl --fail --silent --show-error http://127.0.0.1:8790/healthz && echo
fi
