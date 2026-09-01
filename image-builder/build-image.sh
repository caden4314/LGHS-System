#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PI_GEN_DIR="${PI_GEN_DIR:-$HOME/pi-gen}"
MODE="auto"
TARGET_HOSTNAME=""

usage() {
    cat <<'EOF'
Usage: build-image.sh [--fresh|--fast] [hostname]

Modes:
  auto     Full build the first time; cached fast rebuild afterward (default)
  --fresh  Rebuild Raspberry Pi OS and LGHS from scratch
  --fast   Reuse completed stage0-stage4 cache and rebuild LGHS + export only

Published LGHS images are fleet-key neutral. The Control Pi generates its
Ed25519 fleet key locally; Student Pis are enrolled once with their per-device
cs_admin password and then switch to public-key-only fleet SSH.
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --fresh) MODE="fresh"; shift ;;
        --fast) MODE="fast"; shift ;;
        -h|--help) usage; exit 0 ;;
        -*) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
        *)
            [[ -z "$TARGET_HOSTNAME" ]] || { echo "Only one hostname may be supplied." >&2; exit 2; }
            TARGET_HOSTNAME="$1"; shift ;;
    esac
done

TARGET_HOSTNAME="${LGHS_HOSTNAME:-${TARGET_HOSTNAME}}"
if [[ -z "$TARGET_HOSTNAME" && -f "${PI_GEN_DIR}/config.lghs" ]]; then
    TARGET_HOSTNAME="$(sed -nE "s/^TARGET_HOSTNAME=['\"]?([^'\"]+)['\"]?$/\1/p" "${PI_GEN_DIR}/config.lghs" | tail -n1)"
fi
[[ -n "$TARGET_HOSTNAME" ]] || TARGET_HOSTNAME="$(hostname)"

HOST_LOWER="$(printf '%s' "$TARGET_HOSTNAME" | tr '[:upper:]' '[:lower:]')"
[[ "$HOST_LOWER" == *cont* ]] && EXPECTED_ROLE="controller" || EXPECTED_ROLE="student"
IMG_NAME="LGHS-${TARGET_HOSTNAME}"
WORK_DIR="${PI_GEN_DIR}/work/${IMG_NAME}"
BASE_CACHE="${WORK_DIR}/stage4/rootfs"
SOURCE_COMMIT="$(git -C "$REPO_ROOT" rev-parse HEAD 2>/dev/null || echo unknown)"
LGHS_STAGE="$REPO_ROOT/image-builder/stage-lghs"

# pi-gen requires a password in order to suppress its first-user rename wizard.
# Generate a one-build-only random value; the final LGHS stage re-locks this
# account and lghs-firstboot-provision installs the real per-device password
# before display-manager/getty are allowed to start.
BUILD_FIRST_USER_PASS="$(python3 - <<'PY'
import secrets
print(secrets.token_urlsafe(48))
PY
)"

printf 'LGHS image build\n'
printf '  Target hostname: %s\n' "$TARGET_HOSTNAME"
printf '  Expected role:   %s\n' "$EXPECTED_ROLE"
printf '  LGHS commit:     %s\n' "$SOURCE_COMMIT"
printf '  pi-gen:          %s\n' "$PI_GEN_DIR"
printf '  Fleet secrets:   none baked into image\n'
printf '  First-run UI:    disabled; LGHS owns provisioning\n'

if [[ ! -d "${PI_GEN_DIR}/.git" ]]; then
    git clone --branch arm64 https://github.com/RPi-Distro/pi-gen.git "$PI_GEN_DIR"
else
    git -C "$PI_GEN_DIR" fetch origin arm64
    git -C "$PI_GEN_DIR" checkout arm64
    git -C "$PI_GEN_DIR" pull --ff-only origin arm64
fi

chmod +x "$LGHS_STAGE/prerun.sh"
chmod +x "$LGHS_STAGE/00-install-lghs/00-run.sh"

# A stale untracked SKIP marker on the custom stage causes pi-gen to jump
# straight from "Begin stage-lghs" to "End stage-lghs" and export an old
# rootfs. LGHS fast builds must *always* rerun the custom stage.
rm -f "$LGHS_STAGE/SKIP" "$LGHS_STAGE/00-install-lghs/SKIP"

STAGE_FILES="$LGHS_STAGE/00-install-lghs/files"
STAGED_SOURCE="$STAGE_FILES/LGHS-System"
rm -rf "$STAGED_SOURCE" "$STAGE_FILES/fleet-keys"
mkdir -p "$STAGED_SOURCE"
rsync -a --delete \
    --exclude '.git/' \
    --exclude 'image-builder/stage-lghs/00-install-lghs/files/' \
    --exclude 'work/' --exclude 'deploy/' \
    "$REPO_ROOT/" "$STAGED_SOURCE/"
printf '%s\n' "$SOURCE_COMMIT" > "$STAGED_SOURCE/.lghs-source-commit"

# Only export the final LGHS stage.
touch "$PI_GEN_DIR/stage2/SKIP_IMAGES" "$PI_GEN_DIR/stage4/SKIP_IMAGES" "$PI_GEN_DIR/stage5/SKIP_IMAGES"

cat > "$PI_GEN_DIR/config.lghs" <<EOF
IMG_NAME='${IMG_NAME}'
RELEASE='trixie'
ARCH='arm64'
TARGET_HOSTNAME='${TARGET_HOSTNAME}'
FIRST_USER_NAME='lg_cs_cont'
FIRST_USER_PASS='${BUILD_FIRST_USER_PASS}'
DISABLE_FIRST_BOOT_USER_RENAME=1
PASSWORDLESS_SUDO=0
ENABLE_CLOUD_INIT=0
ENABLE_SSH=1
LOCALE_DEFAULT='en_US.UTF-8'
KEYBOARD_KEYMAP='us'
KEYBOARD_LAYOUT='English (US)'
TIMEZONE_DEFAULT='America/Chicago'
WPA_COUNTRY='US'
STAGE_LIST='stage0 stage1 stage2 stage3 stage4 ${LGHS_STAGE}'
DEPLOY_COMPRESSION='zip'
COMPRESSION_LEVEL='1'
EOF

if [[ "$MODE" == "auto" ]]; then
    [[ -f "$BASE_CACHE/etc/os-release" ]] && MODE="fast" || MODE="fresh"
fi

SKIP_FILES=()
cleanup() {
    local f
    for f in "${SKIP_FILES[@]:-}"; do rm -f "$f"; done
    # Never leave the temporary build password behind in config.lghs.
    if [[ -f "$PI_GEN_DIR/config.lghs" ]]; then
        sed -i '/^FIRST_USER_PASS=/d' "$PI_GEN_DIR/config.lghs" 2>/dev/null || true
    fi
    BUILD_FIRST_USER_PASS=''
}
trap cleanup EXIT INT TERM

if [[ "$MODE" == "fast" ]]; then
    [[ -f "$BASE_CACHE/etc/os-release" ]] || { echo "No completed stage4 cache; run --fresh once." >&2; exit 1; }
    echo
    echo "FAST REBUILD MODE"
    for stage in stage0 stage1 stage2 stage3 stage4; do
        skip_file="$PI_GEN_DIR/$stage/SKIP"
        if [[ ! -e "$skip_file" ]]; then touch "$skip_file"; SKIP_FILES+=("$skip_file"); fi
    done
    BUILD_ENV=(CLEAN=1)
else
    echo
    echo "FULL BUILD MODE"
    rm -rf "$WORK_DIR"
    BUILD_ENV=(CLEAN=0)
fi

find "$PI_GEN_DIR/deploy" -maxdepth 1 -type f \
    \( -name "*${IMG_NAME}*" -o -name "*${TARGET_HOSTNAME}*" \) -delete 2>/dev/null || true

printf '\nBuild mode: %s\n\n' "$MODE"
cd "$PI_GEN_DIR"
sudo env "${BUILD_ENV[@]}" ./build.sh -c config.lghs

# Never bless an export whose custom LGHS stage did not actually install the
# source revision requested by this build.
BUILT_COMMIT_FILE="$WORK_DIR/stage-lghs/rootfs/etc/lghs/source-commit"
[[ -f "$BUILT_COMMIT_FILE" ]] || {
    echo "ERROR: LGHS stage did not produce /etc/lghs/source-commit; refusing build output." >&2
    exit 1
}
BUILT_COMMIT="$(tr -d '[:space:]' < "$BUILT_COMMIT_FILE")"
[[ "$BUILT_COMMIT" == "$SOURCE_COMMIT" ]] || {
    echo "ERROR: LGHS stage is stale: expected $SOURCE_COMMIT, got $BUILT_COMMIT" >&2
    exit 1
}

echo "LGHS stage verification: $BUILT_COMMIT"
printf '\nLGHS build finished. Output files:\n'
find "$PI_GEN_DIR/deploy" -maxdepth 1 -type f -printf '  %f\n' | sort
