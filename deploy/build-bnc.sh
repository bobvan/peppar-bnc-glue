#!/bin/bash
# Source-build BNC (BKG NTRIP Client) when no apt package is available.
#
# BNC source: https://software.rtcm-ntrip.org/svn/trunk/BNC
# Mirror docs: https://igs.bkg.bund.de/ntrip/bnc
#
# Requires the Qt5 toolchain installed by deploy/install-ptpmon.sh.

set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BUILD_DIR="${REPO_DIR}/build/bnc"
BNC_SVN="https://software.rtcm-ntrip.org/svn/trunk/BNC"

# TODO(charlie 2026-04-26): exact build steps need verification on first
# run on ptpmon.  BKG ships an SVN-only source tree; alternatively,
# https://github.com/Cppxx/BNC mirrors a recent snapshot but isn't
# upstream.  Confirm which path produces a working binary on
# Debian Trixie / Ubuntu 24.04 with Qt5.
#
# Skeleton:
#
# mkdir -p "${BUILD_DIR}"
# cd "${BUILD_DIR}"
# svn co "${BNC_SVN}" .
# qmake bnc.pro
# make -j$(nproc)
# sudo install -m 0755 bnc /usr/local/bin/bnc
#
# Verify:
# bnc --help | head -5
#
# This script will be filled in during ptpmon bring-up.

echo "build-bnc.sh: deferred (placeholder; needs first-run verification)."
echo "  Skipping for now.  BNC will not be available until this script"
echo "  is filled in.  The rest of the install (apt deps, venv, systemd"
echo "  units, F9T config) can complete without it; str2str-only smoke"
echo "  testing of the RTCM 3 stream is possible without BNC."
exit 0
