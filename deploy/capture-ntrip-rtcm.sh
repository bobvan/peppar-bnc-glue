#!/bin/bash
# Capture an NTRIP RTCM 3 stream to a timestamped file, with hourly
# (or configurable) rotation via systemd Restart=always.
#
# Designed to run as a user systemd service on gt (no sudo needed).
# ptpmon's caster has no auth, so no credentials in the request.
#
# Behavior:
#   - Opens NTRIP/1.0 GET request to HOST:PORT/MOUNT via nc.
#   - Streams response bytes (including the ~14-byte NTRIP header
#     "ICY 200 OK\r\n\r\n") to a file named with the start
#     timestamp.
#   - Holds the connection open for ROTATE_SECONDS, then exits.
#   - systemd's Restart=always immediately starts a new invocation
#     with a fresh filename → hourly rotation.
#
# Note on header bytes: the captured file starts with the NTRIP/1.0
# response header.  Downstream tools that want pure RTCM 3 should
# skip until the first 0xD3 sync byte.  Most RTCM 3 parsers
# (RTKLIB, BNC) tolerate junk before sync.
#
# Usage:
#   capture-ntrip-rtcm.sh                    # defaults: ptpmon:2102/F9T_PTPMON
#   HOST=foo PORT=2101 MOUNT=BAR ./capture-ntrip-rtcm.sh
#   ARCHIVE_DIR=/path ROTATE_SECONDS=900 ./capture-ntrip-rtcm.sh

set -euo pipefail

HOST="${HOST:-ptpmon}"
PORT="${PORT:-2102}"
MOUNT="${MOUNT:-F9T_PTPMON}"
ARCHIVE_DIR="${ARCHIVE_DIR:-/home/bob/gt/rtcm-archive/ptpmon}"
ROTATE_SECONDS="${ROTATE_SECONDS:-3600}"
USER_AGENT="${USER_AGENT:-gt-rtcm-archive/1.0}"

mkdir -p "$ARCHIVE_DIR"
ts=$(date -u +%Y%m%dT%H%MZ)
out="$ARCHIVE_DIR/${MOUNT}-${ts}.rtcm3"

echo "rtcm-archive: $HOST:$PORT/$MOUNT -> $out for ${ROTATE_SECONDS}s"

# The pipeline:
#   - Subshell prints the NTRIP request, then sleeps for the rotation
#     interval.  The sleep keeps the upstream of nc's stdin alive so
#     nc doesn't close the TCP connection on EOF.
#   - nc opens the TCP socket; the printf sends the request; the
#     response (header + RTCM bytes) flows to stdout, redirected to
#     the file.
#   - timeout is a safety belt: if anything hangs past
#     ROTATE_SECONDS+30, force the kill so systemd can restart.
( printf 'GET /%s HTTP/1.0\r\nUser-Agent: %s\r\n\r\n' "$MOUNT" "$USER_AGENT"
  sleep "$ROTATE_SECONDS"
) | timeout --kill-after=10 "$((ROTATE_SECONDS + 30))" nc "$HOST" "$PORT" \
  > "$out"

# When sleep finishes, nc's stdin EOFs, nc closes the TCP connection,
# script exits cleanly.  Size logged for the journal.
size=$(stat -c %s "$out" 2>/dev/null || echo 0)
echo "rtcm-archive: closed $out ($size bytes, ~$((size * 8 / 1000 / ROTATE_SECONDS)) bps avg)"
