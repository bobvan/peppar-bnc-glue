#!/bin/bash
# Source-build CNES PPP-Wizard demonstrator.
#
# Source:  http://www.ppp-wizard.net/package.html
# License: research use only (NOT OSI).
# Reference: Laurichesse & Privat 2015 ION GNSS paper, "Open-source PPP Client".
#
# PPP-Wizard is a self-sufficient C++ library — no external deps per
# the 2015 paper.  Builds with a single `make` after extracting the
# tarball.  The build produces a static library `libpppw.a` and a
# demo binary `pppw_demo` linked against it; BNC's rtrover backend
# loads the library at runtime.

set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BUILD_DIR="${REPO_DIR}/build/ppp-wizard"
PPPW_URL="http://www.ppp-wizard.net/Articles/RTKLIB_Demo5_Wizard_Hardlink.tgz"
# TODO(charlie 2026-04-26): the canonical download URL changes per
# release on ppp-wizard.net/package.html.  Confirm current filename
# at build time; the placeholder above is the stable hardlink form
# but may not be current.  Pin a SHA256 once a known-working release
# is verified.

# TODO(charlie 2026-04-26): exact build steps need verification on
# first run on ptpmon.
#
# Skeleton:
#
# mkdir -p "${BUILD_DIR}"
# cd "${BUILD_DIR}"
# wget "${PPPW_URL}"
# tar xzf "$(basename ${PPPW_URL})"
# cd PPPWizard
# make -j$(nproc)
# sudo install -m 0644 libpppw.a /usr/local/lib/
# sudo install -m 0755 pppw_demo /usr/local/bin/
# sudo cp -r include/* /usr/local/include/
#
# Then BNC's rtrover.cpp must be compiled against /usr/local/include
# headers and linked against /usr/local/lib/libpppw.a — see
# build-bnc.sh for that wiring.

echo "build-ppp-wizard.sh: not yet implemented (placeholder)"
echo "Manual instructions in the source comments above."
echo ""
echo "Note: PPP-Wizard is research-use-only (not OSI).  Read the"
echo "license at ppp-wizard.net before redistributing build outputs."
exit 1
