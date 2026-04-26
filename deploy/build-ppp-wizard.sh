#!/bin/bash
# Source-build CNES PPP-Wizard demonstrator.
#
# IMPORTANT: PPP-Wizard is NOT publicly downloadable via wget/curl.
# CNES distributes it on request to track interested users.
# Confirmed 2026-04-26: ppp-wizard.net/package.html returns 404,
# the homepage has no download links, and the project's news page
# directs all questions to contact_ppp@cnes.fr.
#
# To obtain the tarball:
#
#   1. Email contact_ppp@cnes.fr asking for the PPP-Wizard
#      demonstrator C++ library + sample code.  Reference the
#      Laurichesse & Privat 2015 ION-GNSS paper "Open-source PPP
#      Client Implementation for the CNES PPP-WIZARD Demonstrator"
#      and / or the 2023 MDPI paper "Recent Advances of the
#      PPP-WIZARD Demonstrator" (Remote Sensing 15:4231).
#
#   2. CNES typically responds with a download link.
#
#   3. Place the tarball at ~/peppar-bnc-glue/build/ppp-wizard.tgz
#      (or override PPPW_TARBALL env var below).
#
#   4. Re-run this script.
#
# License: research use only (NOT OSI).  Read the bundled license
# before redistributing build outputs.
#
# Without PPP-Wizard, BNC still does float PPP via its own internal
# implementation — that's enough for first-light cross-engine
# comparison.  PPP-Wizard is the upgrade path to integer AR.

set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BUILD_DIR="${REPO_DIR}/build/ppp-wizard"
PPPW_TARBALL="${PPPW_TARBALL:-${REPO_DIR}/build/ppp-wizard.tgz}"

if [[ ! -f "${PPPW_TARBALL}" ]]; then
    cat <<EOF >&2

PPP-Wizard tarball not found at ${PPPW_TARBALL}.

PPP-Wizard is request-only — CNES distributes via email to track users.
See the comments at the top of this script for the request procedure.

Skipping PPP-Wizard build.  BNC will still build and run with its
internal float-PPP engine; PPP-Wizard is only needed for integer-AR
upgrade.

EOF
    exit 0   # not a failure — BNC build can proceed without it
fi

# TODO(charlie): once a real PPP-Wizard tarball is in hand, fill in
# the build steps below.  Approximate flow per the 2015 paper and
# typical C++ static-library packaging:
#
# mkdir -p "${BUILD_DIR}"
# cd "${BUILD_DIR}"
# tar xzf "${PPPW_TARBALL}"
# cd PPPWizard*/
# make -j$(nproc)
# sudo install -m 0644 libpppw.a /usr/local/lib/
# sudo install -m 0755 pppw_demo /usr/local/bin/    # if the demo binary exists
# sudo cp -r include/* /usr/local/include/

echo "build-ppp-wizard.sh: tarball present at ${PPPW_TARBALL}, but"
echo "build steps need filling in once we have an actual tarball to"
echo "verify against.  Stopping for now — TODO marker in source."
exit 0
