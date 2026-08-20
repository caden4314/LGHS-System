#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PI_GEN_DIR="${PI_GEN_DIR:-$HOME/pi-gen}"
KEY_STORE="${LGHS_KEY_STORE:-$HOME/.config/lghs/image-secrets}"
FLEET_KEY="${KEY_STORE}/controller_ed25519"
MODE="auto"
TARGET_HOSTNAME=""

usage() {
    cat <<'EOF'
Usage: build-image.sh [--fresh|--fast] [hostname]

Modes:
  auto     Full build the first time; cached fast rebuild afterward (default)
  --fresh  Rebuild Raspberry Pi OS and LGHS from scratch
  --fast   Reuse completed stage0-stage4 cache and rebuild LGHS + export only

The first run creates a persistent fleet SSH key under ~/.config/lghs/image-secrets.
Controller images receive the private key; student images receive only its public key.
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

printf 'LGHS image build\n'
printf '  Target hostname: %s\n' "$TARGET_HOSTNAME"
printf '  Expected role:   %s\n' "$EXPECTED_ROLE"
printf '  LGHS commit:     %s\n' "$SOURCE_COMMIT"
printf '  pi-gen:          %s\n' "$PI_GEN_DIR"

if [[ ! -d "${PI_GEN_DIR}/.git" ]]; then
    git clone --branch arm64 https://github.com/RPi-Distro/pi-gen.git "$PI_GEN_DIR"
else
    git -C "$PI_GEN_DIR" fetch origin arm64
    git -C "$PI_GEN_DIR" checkout arm64
    git -C "$PI_GEN_DIR" pull --ff-only origin arm64
fi

# One persistent classroom fleet keypair is reused for all images built here.
install -d -m 0700 "$KEY_STORE"
if [[ ! -f "$FLEET_KEY" ]]; then
    echo "Creating LGHS fleet SSH keypair in $KEY_STORE"
    ssh-keygen -q -t ed25519 -N '' -C 'LGHS fleet controller' -f "$FLEET_KEY"
fi
chmod 0600 "$FLEET_KEY"
chmod 0644 "$FLEET_KEY.pub"
printf '  Fleet key:       %s\n' "$FLEET_KEY.pub"

chmod +x "$REPO_ROOT/image-builder/stage-lghs/prerun.sh"
chmod +x "$REPO_ROOT/image-builder/stage-lghs/00-install-lghs/00-run.sh"

STAGE_FILES="$REPO_ROOT/image-builder/stage-lghs/00-install-lghs/files"
STAGED_SOURCE="$STAGE_FILES/LGHS-System"
STAGED_KEYS="$STAGE_FILES/fleet-keys"
rm -rf "$STAGED_SOURCE" "$STAGED_KEYS"
mkdir -p "$STAGED_SOURCE" "$STAGED_KEYS"

rsync -a --delete \
    --exclude '.git/' \
    --exclude 'image-builder/stage-lghs/00-install-lghs/files/' \
    --exclude 'work/' --exclude 'deploy/' \
    "$REPO_ROOT/" "$STAGED_SOURCE/"
printf '%s\n' "$SOURCE_COMMIT" > "$STAGED_SOURCE/.lghs-source-commit"
install -m 0600 "$FLEET_KEY" "$STAGED_KEYS/controller_ed25519"
install -m 0644 "$FLEET_KEY.pub" "$STAGED_KEYS/controller_ed25519.pub"

# Only export the final LGHS stage.
touch "$PI_GEN_DIR/stage2/SKIP_IMAGES" "$PI_GEN_DIR/stage4/SKIP_IMAGES" "$PI_GEN_DIR/stage5/SKIP_IMAGES"

cat > "$PI_GEN_DIR/config.lghs" <<EOF
IMG_NAME='${IMG_NAME}'
RELEASE='trixie'
ARCH='arm64'
TARGET_HOSTNAME='${TARGET_HOSTNAME}'
FIRST_USER_NAME='lg_cs_cont'
ENABLE_SSH=1
LOCALE_DEFAULT='en_US.UTF-8'
KEYBOARD_KEYMAP='us'
KEYBOARD_LAYOUT='English (US)'
TIMEZONE_DEFAULT='America/Chicago'
WPA_COUNTRY='US'
STAGE_LIST='stage0 stage1 stage2 stage3 stage4 ${REPO_ROOT}/image-builder/stage-lghs'
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
    rm -rf "$STAGED_KEYS"
}
trap cleanup EXIT INT TERM

if [[ "$MODE" == "fast" ]]; then
    [[ -f "$BASE_CACHE/etc/os-release" ]] || { echo "No completed stage4 cache; run --fresh once." >&2; exit 1; }
    echo
    echo "FAST REBUILD MODE"
    echo "  Reusing completed Raspberry Pi OS stage0-stage4 cache."
    echo "  Rebuilding LGHS customization and final image export."
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

printf '\nBuild mode: %s\n' "$MODE"
printf 'Fleet SSH enrollment: enabled\n'
printf 'Compression level: 1\n\n'

cd "$PI_GEN_DIR"
sudo env "${BUILD_ENV[@]}" ./build.sh -c config.lghs

printf '\nLGHS build finished. Output files:\n'
find "$PI_GEN_DIR/deploy" -maxdepth 1 -type f -printf '  %f\n' | sort
