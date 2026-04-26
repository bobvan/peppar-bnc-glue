#!/bin/bash
# Install BKG NTRIP Client (BNC).
#
# Default path: prebuilt Debian 12 binary from BKG.  Confirmed
# working on Ubuntu 24.04 noble (libQt5* shared libs present from
# qtbase5-dev + libqt5* packages installed by install-ptpmon.sh).
#
# Source-build path: only needed if linking PPP-Wizard backend
# for integer AR (the prebuilt binary uses BNC's internal float
# PPP only, which is what we want for first-light validation).
#
# BNC source: https://software.rtcm-ntrip.org/svn/trunk/BNC
# (SVN, requires auth) or https://github.com/mlytvyn80/bnc (mirror).
# Source build deferred to a follow-up branch when PPP-Wizard
# tarball arrives — see deploy/build-ppp-wizard.sh.

set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BUILD_DIR="${REPO_DIR}/build/bnc"
BNC_VERSION="${BNC_VERSION:-2.13.4}"
BNC_URL="https://igs.bkg.bund.de/root_ftp/NTRIP/software/BNC/bnc-${BNC_VERSION}-debian12.zip"

if command -v bnc >/dev/null 2>&1; then
    echo "BNC already installed: $(command -v bnc) ($(bnc --version 2>&1 | head -1))"
    echo "Re-run with --force to reinstall."
    [[ "${1:-}" == "--force" ]] || exit 0
fi

mkdir -p "${BUILD_DIR}"
cd "${BUILD_DIR}"

if [[ ! -f "bnc-${BNC_VERSION}-debian12.zip" ]]; then
    echo "Downloading BNC ${BNC_VERSION} (Debian 12 prebuilt) from BKG…"
    curl -sS -fL -o "bnc-${BNC_VERSION}-debian12.zip" "${BNC_URL}"
fi

if [[ ! -f "bnc-${BNC_VERSION}" ]]; then
    if ! command -v unzip >/dev/null 2>&1; then
        echo "Installing unzip…"
        sudo apt-get install -y unzip
    fi
    unzip -oq "bnc-${BNC_VERSION}-debian12.zip"
fi

sudo install -m 0755 "bnc-${BNC_VERSION}" /usr/local/bin/bnc
sudo mkdir -p /usr/local/share/bnc
for f in LICENSE CHANGELOG.md README; do
    [[ -f "$f" ]] && sudo install -m 0644 "$f" /usr/local/share/bnc/
done

echo "BNC ${BNC_VERSION} installed at /usr/local/bin/bnc"
bnc --version 2>&1 | head -1
