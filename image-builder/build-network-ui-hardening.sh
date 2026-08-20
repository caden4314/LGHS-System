#!/usr/bin/env bash
set -euo pipefail

PIN="9064d7b4f9c3c841bfd195dae9e0bf8110412d0f"
WORK=/tmp/lghs-pplug-netman
HARDENED=/usr/local/lib/lghs/libnetman.so.hardened
APPLY=/usr/local/sbin/lghs-network-ui-apply

[[ $EUID -eq 0 ]] || { echo "Run as root" >&2; exit 1; }

# Controller images keep the normal Raspberry Pi network UI.
if [[ "$(cat /etc/lghs/role 2>/dev/null || true)" != "student" ]]; then
    echo "LGHS: controller image; network UI patch not required."
    exit 0
fi

manual_before="$(mktemp)"
apt-mark showmanual | sort > "$manual_before"
cleanup() {
    rm -rf "$WORK" "$manual_before"
}
trap cleanup EXIT

apt-get update
DEBIAN_FRONTEND=noninteractive apt-get install -y \
    git meson ninja-build build-essential pkg-config \
    libgtk-3-dev libgtkmm-3.0-dev libnm-dev libnma-dev libsecret-1-dev \
    lxpanel-dev wf-panel-pi

rm -rf "$WORK"
git clone -q https://github.com/raspberrypi-ui/pplug-netman.git "$WORK"
git -C "$WORK" checkout -q "$PIN"

python3 - "$WORK/src/applet.c" <<'PY'
from pathlib import Path
import re, sys
p = Path(sys.argv[1])
s = p.read_text(encoding='utf-8')

# Hide both the normal-menu and VPN-menu Edit Connections entries for the
# classroom student account, while leaving the Wi-Fi picker and activation UI.
pattern = re.compile(
    r"(?P<indent>\t)/\* 'Edit Connections\.\.\.' item \*/\n"
    r"(?P<body>\tapplet->connections_menu_item = gtk_menu_item_new_with_mnemonic \(_\(\"Edit Connections…\"\)\);\n"
    r"\tg_signal_connect \(applet->connections_menu_item,\n"
    r"\t+\s*\"activate\",\n"
    r"\t+\s*G_CALLBACK \(nma_edit_connections_cb\),\n"
    r"\t+\s*applet\);\n"
    r"\tgtk_menu_shell_append \((?P<shell>[^\n]+), applet->connections_menu_item\);)"
)

def repl(m):
    body = m.group('body')
    indented = '\n'.join('\t' + line for line in body.splitlines())
    return (
        "\t/* 'Edit Connections...' item - hidden from LGHS student account */\n"
        "\tif (g_strcmp0 (g_get_user_name (), \"lg_cs_cont\") != 0)\n"
        "\t{\n" + indented + "\n\t}\n"
        "\telse\n\t{\n\t\tapplet->connections_menu_item = NULL;\n\t}"
    )

s2, count = pattern.subn(repl, s)
if count != 2:
    raise SystemExit(f'Expected to patch 2 Edit Connections blocks, patched {count}')
p.write_text(s2, encoding='utf-8')
print('LGHS: patched both Edit Connections menu entries.')
PY

# Build only against the target image's installed Raspberry Pi desktop stack.
meson setup "$WORK/build" "$WORK" --prefix=/usr --buildtype=release
ninja -C "$WORK/build"

built="$(find "$WORK/build" -type f -name libnetman.so -print -quit)"
[[ -n "$built" && -f "$built" ]] || { echo "LGHS: patched libnetman.so was not produced" >&2; exit 1; }
install -d -m 0755 /usr/local/lib/lghs
install -m 0644 "$built" "$HARDENED"

[[ -x "$APPLY" ]] || { echo "LGHS: missing $APPLY" >&2; exit 1; }
"$APPLY"

# Remove development-only packages that were introduced solely for this build.
manual_after="$(mktemp)"
apt-mark showmanual | sort > "$manual_after"
comm -13 "$manual_before" "$manual_after" | while read -r pkg; do
    case "$pkg" in
        git|meson|ninja-build|build-essential|pkg-config|libgtk-3-dev|libgtkmm-3.0-dev|libnm-dev|libnma-dev|libsecret-1-dev|lxpanel-dev)
            apt-mark auto "$pkg" >/dev/null 2>&1 || true
            ;;
    esac
done
rm -f "$manual_after"
DEBIAN_FRONTEND=noninteractive apt-get autoremove --purge -y
apt-get clean
rm -rf /var/lib/apt/lists/*

echo "LGHS: student network UI hardening baked into image."
