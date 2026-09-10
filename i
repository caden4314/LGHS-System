#!/usr/bin/env bash
set -euo pipefail

INSTALL_URL="https://raw.githubusercontent.com/caden4314/LGHS-System/main/bootstrap/install-stock.sh"
TMP="$(mktemp /tmp/lghs-stock.XXXXXX.sh)"
cleanup() { rm -f "$TMP"; }
trap cleanup EXIT

if [[ ! -r /dev/tty ]]; then
  printf 'LGHS: an interactive terminal is required for provisioning.\n' >&2
  exit 1
fi

printf 'LGHS: downloading stock installer...\n'
curl -fsSL "$INSTALL_URL" -o "$TMP"
chmod 0700 "$TMP"

if [[ ${EUID:-$(id -u)} -eq 0 ]]; then
  bash "$TMP" </dev/tty
else
  sudo -v
  sudo bash "$TMP" </dev/tty
fi
