#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PI_GEN_DIR="${PI_GEN_DIR:-$HOME/pi-gen}"
TARGET_HOSTNAME="${LGHS_HOSTNAME:-${1:-}}"

if [[ -z "${TARGET_HOSTNAME}" && -f "${PI_GEN_DIR}/config" ]]; then
    TARGET_HOSTNAME="$(sed -nE "s/^TARGET_HOSTNAME=['\"]?([^'\"]+)['\"]?$/\1/p" "${PI_GEN_DIR}/config" | tail -n1)"
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

# pi-gen expects stage scripts to be executable. GitHub's simple contents API
# may not preserve that mode, so normalize it locally before every build.
chmod +x "${REPO_ROOT}/image-builder/stage-lghs/prerun.sh"
chmod +x "${REPO_ROOT}/image-builder/stage-lghs/00-install-lghs/00-run.sh"

STAGED_SOURCE="${REPO_ROOT}/image-builder/stage-lghs/00-install-lghs/files/LGHS-System"
rm -rf "${STAGED_SOURCE}"
mkdir -p "${STAGED_SOURCE}"

# Snapshot the current LGHS tree into the pi-gen stage, but do not recursively
# copy the generated staged snapshot or local build products.
rsync -a \
    --exclude '.git/' \
    --exclude 'image-builder/stage-lghs/00-install-lghs/files/' \
    --exclude 'work/' \
    --exclude 'deploy/' \
    "${REPO_ROOT}/" "${STAGED_SOURCE}/"

# We only want the final LGHS image exported, not the stock stage4 image.
touch "${PI_GEN_DIR}/stage4/SKIP_IMAGES"

cat > "${PI_GEN_DIR}/config.lghs" <<EOF
IMG_NAME='LGHS-${TARGET_HOSTNAME}'
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
EOF

printf '\nBuild configuration written to %s/config.lghs\n' "${PI_GEN_DIR}"
printf 'The LGHS stage will independently verify /etc/hostname and choose the role.\n\n'

cd "${PI_GEN_DIR}"
sudo ./build.sh -c config.lghs

printf '\nLGHS build finished. Output files:\n'
find "${PI_GEN_DIR}/deploy" -maxdepth 1 -type f -printf '  %f\n' | sort
