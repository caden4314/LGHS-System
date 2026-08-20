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

Examples:
  bash image-builder/build-image.sh LGCSCONT
  bash image-builder/build-image.sh --fast LGCSCONT
  bash image-builder/build-image.sh --fresh LGCSCONT
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --fresh)
            MODE="fresh"
            shift
            ;;
        --fast)
            MODE="fast"
            shift
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        -* )
            echo "Unknown option: $1" >&2
            usage >&2
            exit 2
            ;;
        *)
            if [[ -n "${TARGET_HOSTNAME}" ]]; then
                echo "Only one hostname may be supplied." >&2
                exit 2
            fi
            TARGET_HOSTNAME="$1"
            shift
            ;;
    esac
done

TARGET_HOSTNAME="${LGHS_HOSTNAME:-${TARGET_HOSTNAME}}"

if [[ -z "${TARGET_HOSTNAME}" && -f "${PI_GEN_DIR}/config.lghs" ]]; then
    TARGET_HOSTNAME="$(sed -nE "s/^TARGET_HOSTNAME=['\"]?([^'\"]+)['\"]?$/\1/p" "${PI_GEN_DIR}/config.lghs" | tail -n1)"
fi

if [[ -z "${TARGET_HOSTNAME}" ]]; then
    TARGET_HOSTNAME="$(hostname)"
fi

HOST_LOWER="$(printf '%s' "${TARGET_HOSTNAME}" | tr '[:upper:]' '[:lower:]')"
if [[ "${HOST_LOWER}" == *cont* ]]; then
    EXPECTED_ROLE="controller"
else
    EXPECTED_ROLE="student"
fi

IMG_NAME="LGHS-${TARGET_HOSTNAME}"
WORK_DIR="${PI_GEN_DIR}/work/${IMG_NAME}"
BASE_CACHE="${WORK_DIR}/stage4/rootfs"

printf 'LGHS image build\n'
printf '  Target hostname: %s\n' "${TARGET_HOSTNAME}"
printf '  Expected role:   %s\n' "${EXPECTED_ROLE}"
printf '  pi-gen:          %s\n' "${PI_GEN_DIR}"

if [[ ! -d "${PI_GEN_DIR}/.git" ]]; then
    echo "pi-gen not found; cloning official arm64 branch..."
    git clone --branch arm64 https://github.com/RPi-Distro/pi-gen.git "${PI_GEN_DIR}"
else
    echo "Updating existing pi-gen checkout..."
    git -C "${PI_GEN_DIR}" fetch origin arm64
    git -C "${PI_GEN_DIR}" checkout arm64
    git -C "${PI_GEN_DIR}" pull --ff-only origin arm64
fi

chmod +x "${REPO_ROOT}/image-builder/stage-lghs/prerun.sh"
chmod +x "${REPO_ROOT}/image-builder/stage-lghs/00-install-lghs/00-run.sh"

STAGED_SOURCE="${REPO_ROOT}/image-builder/stage-lghs/00-install-lghs/files/LGHS-System"
rm -rf "${STAGED_SOURCE}"
mkdir -p "${STAGED_SOURCE}"

rsync -a \
    --delete \
    --exclude '.git/' \
    --exclude 'image-builder/stage-lghs/00-install-lghs/files/' \
    --exclude 'work/' \
    --exclude 'deploy/' \
    "${REPO_ROOT}/" "${STAGED_SOURCE}/"

# Only export the final LGHS stage, never intermediate stock images.
touch "${PI_GEN_DIR}/stage2/SKIP_IMAGES"
touch "${PI_GEN_DIR}/stage4/SKIP_IMAGES"
touch "${PI_GEN_DIR}/stage5/SKIP_IMAGES"

cat > "${PI_GEN_DIR}/config.lghs" <<EOF
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

if [[ "${MODE}" == "auto" ]]; then
    if [[ -f "${BASE_CACHE}/etc/os-release" ]]; then
        MODE="fast"
    else
        MODE="fresh"
    fi
fi

SKIP_FILES=()
cleanup_skip_files() {
    local f
    for f in "${SKIP_FILES[@]:-}"; do
        rm -f "$f"
    done
}
trap cleanup_skip_files EXIT INT TERM

if [[ "${MODE}" == "fast" ]]; then
    if [[ ! -f "${BASE_CACHE}/etc/os-release" ]]; then
        echo "Fast build requested, but no completed stage4 cache exists:" >&2
        echo "  ${BASE_CACHE}" >&2
        echo "Run once with --fresh first." >&2
        exit 1
    fi

    echo
    echo "FAST REBUILD MODE"
    echo "  Reusing completed Raspberry Pi OS stage0-stage4 cache."
    echo "  Rebuilding LGHS customization and final image export."
    echo "  No software or image content is being omitted."

    for stage in stage0 stage1 stage2 stage3 stage4; do
        skip_file="${PI_GEN_DIR}/${stage}/SKIP"
        if [[ ! -e "${skip_file}" ]]; then
            touch "${skip_file}"
            SKIP_FILES+=("${skip_file}")
        fi
    done

    BUILD_ENV=(CLEAN=1)
else
    echo
    echo "FULL BUILD MODE"
    echo "  Rebuilding Raspberry Pi OS stage0-stage4 and LGHS."
    rm -rf "${WORK_DIR}"
    BUILD_ENV=(CLEAN=0)
fi

# Remove previous exported files for this image name so the result is unambiguous.
find "${PI_GEN_DIR}/deploy" -maxdepth 1 -type f \
    \( -name "*${IMG_NAME}*" -o -name "*${TARGET_HOSTNAME}*" \) \
    -delete 2>/dev/null || true

printf '\nBuild configuration: %s/config.lghs\n' "${PI_GEN_DIR}"
printf 'Build mode:          %s\n' "${MODE}"
printf 'Compression level:   1 (faster ZIP, identical image contents)\n'
printf 'LGHS stage verifies /etc/hostname and chooses the role itself.\n\n'

cd "${PI_GEN_DIR}"
sudo env "${BUILD_ENV[@]}" ./build.sh -c config.lghs

printf '\nLGHS build finished. Output files:\n'
find "${PI_GEN_DIR}/deploy" -maxdepth 1 -type f -printf '  %f\n' | sort
