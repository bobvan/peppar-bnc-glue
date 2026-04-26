#!/bin/bash
# Launch BNC for ptpmon — reads NTRIP credentials at runtime from the
# engine host's gitignored ntrip*.conf files and exec's BNC headless.
#
# Called by deploy/systemd/bnc-ptpmon.service ExecStart.
#
# Why a wrapper script instead of systemd EnvironmentFile + literal
# ExecStart: BNC's --key flag value (mountPoints) is a single
# semicolon-separated string with embedded user:pass URLs.  Composing
# that via systemd's argv expansion is brittle when the password has
# special characters, and EnvironmentFile parsing has its own
# quirks.  A wrapper is clearer.
#
# CREDENTIAL EXPOSURE: this approach puts the user:pass for both
# CNES and BKG into BNC's process cmdline, which is visible to any
# user who can `ps` or read the systemd journal as bob/root.  This
# is acceptable for ptpmon's threat model: anyone with `ps`
# capability already has shell access as bob, and `cat
# /home/bob/peppar-fix/ntrip-cnes.conf` exposes the same secrets
# directly.  We do NOT introduce new attacker classes via this
# wrapper.  An alternative path — write a .conf file to /run/...
# at mode 0600 and let BNC --conf read it — was investigated 2026-
# 04-26 and rejected: BNC's QSettings INI parser silently truncates
# multi-element semicolon-separated values regardless of "..." or
# \; escaping, leaving only the first stream registered.  The
# --key invocation is the only headless path verified to work
# with multi-stream configurations.
#
# IMPORTANT: do NOT URL-encode the user:pass.  BNC sends the literal
# bytes through HTTP Basic Auth.  Encoding `!` to `%21` produced
# "Unauthorized" responses on BCEP00BKG0 — confirmed 2026-04-26.

set -euo pipefail

CNES_CONF="${CNES_CONF:-/home/bob/peppar-fix/ntrip-cnes.conf}"
BKG_CONF="${BKG_CONF:-/home/bob/peppar-fix/ntrip.conf}"
LOG_DIR="${LOG_DIR:-/home/bob/peppar-bnc-glue/log}"

if [[ ! -f "${CNES_CONF}" ]] || [[ ! -f "${BKG_CONF}" ]]; then
    echo "ERROR: missing ${CNES_CONF} or ${BKG_CONF}" >&2
    exit 1
fi

CNES_USER=$(awk -F"= *" '/^user/     {print $2}' "${CNES_CONF}")
CNES_PASS=$(awk -F"= *" '/^password/ {print $2}' "${CNES_CONF}")
BKG_USER=$( awk -F"= *" '/^user/     {print $2}' "${BKG_CONF}")
BKG_PASS=$( awk -F"= *" '/^password/ {print $2}' "${BKG_CONF}")

mkdir -p "${LOG_DIR}"

# Three streams: local F9T (loopback, no auth), CNES corrections,
# BKG broadcast eph.  Format per element:
#   //USER:PASS@HOST:PORT/MOUNT FORMAT COUNTRY LAT LON nmea NTRIPVER
MOUNTPOINTS="//:@127.0.0.1:2102/F9T_PTPMON RTCM_3.3 USA 38.00 -122.00 no 1"
MOUNTPOINTS+=";//${CNES_USER}:${CNES_PASS}@products.igs-ip.net:443/SSRA00CNE0 RTCM_3.3 FRA 48.00 2.00 no 2s"
MOUNTPOINTS+=";//${BKG_USER}:${BKG_PASS}@ntrip.data.gnss.ga.gov.au:443/BCEP00BKG0 RTCM_3.3 AUS -27.00 153.00 no 2s"

# Headless Qt5 needs offscreen platform on Ubuntu noble without DISPLAY.
export QT_QPA_PLATFORM=offscreen

# autoStart=2 is required for headless: without it, --nw exits with
# code 3 and zero output.
exec /usr/local/bin/bnc --nw \
    --key autoStart 2 \
    --key startTab 13 \
    --key logFile "${LOG_DIR}/bnc.log" \
    --key mountPoints "${MOUNTPOINTS}" \
    --key PPP/dataSource "Real-Time Streams" \
    --key PPP/corrMount SSRA00CNE0 \
    --key PPP/logPath "${LOG_DIR}/" \
    --key PPP/nmeaPath "${LOG_DIR}/" \
    --key PPP/staTable "F9T_PTPMON,100.0,100.0,100.0,100.0,100.0,100.0,0.1,3e-6,0,E:1&C E:7&Q C:2&I C:7&I" \
    --key PPP/lcGalileo "P3&L3" \
    --key PPP/lcBDS "P3&L3" \
    --key PPP/lcGPS "no" \
    --key PPP/lcGLONASS "no"
