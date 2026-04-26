#!/bin/bash
# Install BNC + PPP-Wizard + str2str on ptpmon (or any Debian/Ubuntu host
# with a u-blox ZED-F9T).  apt-first, source-fallback.
#
# Idempotent: each step checks if already installed before doing work.
#
# Usage:
#   ./deploy/install-ptpmon.sh             # install everything
#   ./deploy/install-ptpmon.sh --dry-run   # show what would be done
#
# Exits non-zero on any unrecoverable failure.

set -euo pipefail

DRY_RUN=0
if [[ "${1:-}" == "--dry-run" ]]; then
    DRY_RUN=1
fi

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BUILD_DIR="${REPO_DIR}/build"

run() {
    if [[ ${DRY_RUN} -eq 1 ]]; then
        echo "DRY-RUN: $*"
    else
        echo "+ $*"
        "$@"
    fi
}

require_sudo() {
    if [[ ${DRY_RUN} -eq 0 ]] && ! sudo -n true 2>/dev/null; then
        echo "This step needs passwordless sudo.  Configure or run interactively." >&2
        exit 2
    fi
}

# ── 1. apt deps ───────────────────────────────────────────────────────────── #

echo "==> apt deps"
require_sudo
APT_PKGS=(
    build-essential
    cmake
    git
    qt5-qmake
    qtbase5-dev
    libqt5opengl5-dev
    libqt5network5
    libqt5positioning5-dev
    libqt5serialport5-dev
    libssl-dev
    rtklib
    python3-venv
    python3-pip
)
run sudo apt-get update
run sudo apt-get install -y "${APT_PKGS[@]}"

# ── 2. BNC: try apt, fall back to source ─────────────────────────────────── #

echo "==> BNC"
if command -v bnc >/dev/null 2>&1; then
    echo "BNC already installed: $(command -v bnc)"
elif apt-cache show bnc >/dev/null 2>&1; then
    run sudo apt-get install -y bnc
else
    echo "no apt package for BNC; falling back to source build"
    run "${REPO_DIR}/deploy/build-bnc.sh"
fi

# ── 3. PPP-Wizard: source only ───────────────────────────────────────────── #

echo "==> PPP-Wizard"
if [[ -x /usr/local/lib/libpppw.so ]] || [[ -x /usr/local/bin/pppw_demo ]]; then
    echo "PPP-Wizard appears to be installed at /usr/local"
else
    run "${REPO_DIR}/deploy/build-ppp-wizard.sh"
fi

# ── 4. venv for the adapter ──────────────────────────────────────────────── #

echo "==> Python venv for adapter"
if [[ -d "${REPO_DIR}/venv" ]]; then
    echo "venv already exists at ${REPO_DIR}/venv"
else
    run python3 -m venv "${REPO_DIR}/venv"
fi
if [[ -f "${REPO_DIR}/adapters/requirements.txt" ]]; then
    run "${REPO_DIR}/venv/bin/pip" install --upgrade pip
    run "${REPO_DIR}/venv/bin/pip" install -r "${REPO_DIR}/adapters/requirements.txt"
fi

# ── 5. systemd units ─────────────────────────────────────────────────────── #

echo "==> systemd units"
for unit in str2str-ptpmon.service bnc-ptpmon.service; do
    src="${REPO_DIR}/deploy/systemd/${unit}"
    dst="/etc/systemd/system/${unit}"
    if [[ ! -f "${src}" ]]; then
        echo "WARN: ${src} not present yet; skipping"
        continue
    fi
    run sudo install -m 0644 "${src}" "${dst}"
done
run sudo systemctl daemon-reload

# ── 6. Reminders ──────────────────────────────────────────────────────────── #

cat <<'EOF'

==> Install complete.

Next steps (NOT automated — each is manual / requires lab review):

  1. Copy and edit per-host config:
       cp config/bnc.conf.example config/bnc.conf
       cp config/str2str.args.example config/str2str.args
     Fill in NTRIP credentials, mount paths, BNC PPP options.
     See ntrip.conf credentials in /home/bob/peppar-fix/ on the
     existing lab hosts.

  2. Configure the F9T to emit RTCM 3 MSM7 instead of RAWX/TIM-TP:
       ./deploy/configure-f9t-rtcm.sh
     This is destructive to the existing peppar-fix engine config
     on this F9T — confirm ptpmon is dedicated to BNC use first.

  3. Smoke-test str2str alone:
       systemctl --user start str2str-ptpmon
       (or sudo systemctl start ...)
     Watch /dev/gnss0 → local NTRIP mount come up; verify RTCM 3
     1077/1097/1127/1005 frames flow.

  4. Start BNC:
       sudo systemctl start bnc-ptpmon

  5. Watch BNC's PPP log; verify position converges.  Run the
     adapter to translate to PePPAR-Fix's external-PPP-log schema.

EOF
