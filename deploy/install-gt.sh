#!/bin/bash
# Install the gt-side RTCM archive (no sudo — user systemd).
#
# Per project_to_charlie_gt_rtcm_archive_20260427: continuous
# capture of ptpmon's F9T_PTPMON NTRIP mount to gt's RAIDZ-3 +
# offsite-backed-up storage.
#
# Run this on host gt as user bob (must have linger enabled, which
# it does by default for bob on gt — see `loginctl show-user bob`).

set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
UNIT=rtcm-archive-gt.service
USER_UNIT_DIR="$HOME/.config/systemd/user"
ARCHIVE_DIR="${ARCHIVE_DIR:-/home/bob/gt/rtcm-archive/ptpmon}"

# 1. Verify dependencies
if ! command -v nc >/dev/null; then
    echo "ERROR: nc not found.  apt install netcat-openbsd (needs sudo)." >&2
    exit 1
fi

# 2. Make archive directory
echo "==> archive directory"
mkdir -p "$ARCHIVE_DIR"
echo "    $ARCHIVE_DIR"

# 3. Install user systemd unit by symlink (so repo edits propagate)
echo "==> install user systemd unit"
mkdir -p "$USER_UNIT_DIR"
ln -sf "$REPO_DIR/deploy/systemd/$UNIT" "$USER_UNIT_DIR/$UNIT"
echo "    $USER_UNIT_DIR/$UNIT -> $REPO_DIR/deploy/systemd/$UNIT"

# 4. Verify linger so service runs without active session
if [[ "$(loginctl show-user "$USER" | awk -F= '/^Linger=/{print $2}')" != "yes" ]]; then
    echo "WARN: linger is not enabled for $USER — service will stop on logout" >&2
    echo "      To fix: ask Bob to enable with 'sudo loginctl enable-linger $USER'" >&2
fi

# 5. Reload + enable + start
echo "==> systemctl --user daemon-reload"
systemctl --user daemon-reload

echo "==> enable + start $UNIT"
systemctl --user enable --now "$UNIT"

# 6. Brief status check
sleep 2
echo "==> service state"
systemctl --user is-active "$UNIT"

# 7. Hint on log + file growth
cat <<EOF

Installed and started.

Watch journal:        journalctl --user -u $UNIT -f
List archive files:   ls -la $ARCHIVE_DIR
Service status:       systemctl --user status $UNIT
Stop:                 systemctl --user stop $UNIT
Disable on boot:      systemctl --user disable $UNIT
EOF
