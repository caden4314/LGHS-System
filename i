#!/usr/bin/env bash
set -euo pipefail

INSTALL_URL="https://raw.githubusercontent.com/caden4314/LGHS-System/main/bootstrap/install-stock.sh"
TMP="$(mktemp /tmp/lghs-stock.XXXXXX.sh)"
cleanup() { rm -f "$TMP"; }
trap cleanup EXIT

printf 'LGHS: downloading stock installer...\n'
curl -fsSL "$INSTALL_URL" -o "$TMP"
chmod 0700 "$TMP"

if [[ ${EUID:-$(id -u)} -eq 0 ]]; then
  bash "$TMP"
else
  sudo -v
  sudo bash "$TMP"
fi
