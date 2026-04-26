#!/usr/bin/env python3
"""Configure ptpmon's ZED-F9T-PTP for RTCM 3 MSM7 output mode.

Replaces the peppar-fix engine's UBX (RAWX/TIM-TP/SFRBX) output config
with an RTCM 3 MSM7 stream suitable for BNC consumption.  Saves the
config to BBR + FLASH so it survives reboot.

Usage:
    configure-f9t-rtcm.py /dev/gnss0
    configure-f9t-rtcm.py /dev/gnss0 --dry-run
    configure-f9t-rtcm.py /dev/gnss0 --snapshot-only
    configure-f9t-rtcm.py /dev/gnss0 --revert snapshot.json

Options:
    --dry-run          show CFG-VALSET payloads without sending
    --snapshot-only    poll current config, print to stdout, exit
    --revert FILE      restore config from a previous --snapshot-only output

Constraints reflected in this script:
- ZED-F9T-PTP (TIM 2.20, L2-only) — NAKs L5/E5a/B2a regardless of attempt.
- E810 AQ-mediated I2C — write path works on stock ice driver
  (per project_e810_i2c_write).  Streaming patch breaks writes.
- Save to FLASH so the config survives reboot — this matters because
  the F9T's UBX output keys we are zeroing are the engine's primary
  data path; if we don't save, a reboot reverts to the engine config
  and BNC sees no data until reconfigured.

References:
- u-blox ZED-F9T Interface Description (UBX-20033631)
- PePPAR-Fix scripts/configure_f9t.py — sister script, full engine config
- peppar-bnc-glue config/ptpmon-rtcm.toml — human-readable TOML version

Exit non-zero on any error.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

try:
    import serial
    from pyubx2 import UBXMessage, UBXReader, SET, POLL
except ImportError:
    print("ERROR: requires pyubx2 and pyserial", file=sys.stderr)
    print("  /home/bob/peppar-fix/venv/bin/pip install pyubx2 pyserial",
          file=sys.stderr)
    sys.exit(1)

import os


class KernelGnssFd:
    """Minimal file-like wrapper around a kernel GNSS char device.

    pyserial assumes a tty and tries termios.tcgetattr, which fails with
    'Inappropriate ioctl for device' on /dev/gnss*.  Use raw os.open() +
    os.read()/os.write() instead.  Mirrors PePPAR-Fix's
    scripts/peppar_fix/gnss_stream.py:KernelGnssStream's API surface but
    trimmed to what UBXReader needs (read, write, reset_input_buffer,
    flush, close)."""

    def __init__(self, path: str) -> None:
        self._fd = os.open(path, os.O_RDWR)

    def read(self, n: int = 1) -> bytes:
        # pyubx2 calls read in tight loops; non-blocking would spin.
        # Default kernel char device is blocking, which is what we want.
        try:
            return os.read(self._fd, n)
        except BlockingIOError:
            return b""

    def write(self, data: bytes) -> int:
        return os.write(self._fd, data)

    def reset_input_buffer(self) -> None:
        # Drain anything already queued.  No tcflush; just read what's
        # available with a brief deadline.
        import select
        deadline = time.monotonic() + 0.2
        while time.monotonic() < deadline:
            r, _, _ = select.select([self._fd], [], [], 0.05)
            if not r:
                return
            try:
                os.read(self._fd, 4096)
            except BlockingIOError:
                return

    def flush(self) -> None:
        # os.fsync() returns EINVAL on a char device; writes through
        # the GNSS char device are already synchronous as far as the
        # kernel-userspace boundary is concerned.  No-op.
        pass

    def close(self) -> None:
        try:
            os.close(self._fd)
        except OSError:
            pass


# ── F9T configuration: target state for RTCM 3 output ────────────────────── #
#
# Keyed by CFG-VALSET configuration item names from u-blox interface
# description.  Tuples are (key_id, value).  See config/ptpmon-rtcm.toml
# for human-readable rationale.

# UBX outputs on I2C: ALL DISABLED.  Engine fed off these; BNC does not need
# any of them.  By zeroing on I2C only, the same keys remain available on
# USB / UART if anyone wants to reattach the engine via a different port.
_UBX_OUTPUTS_OFF = [
    ("CFG_MSGOUT_UBX_RXM_RAWX_I2C", 0),
    ("CFG_MSGOUT_UBX_RXM_SFRBX_I2C", 0),
    ("CFG_MSGOUT_UBX_NAV_PVT_I2C", 0),
    ("CFG_MSGOUT_UBX_NAV_SAT_I2C", 0),
    ("CFG_MSGOUT_UBX_TIM_TP_I2C", 0),
]

# RTCM 3 MSM7 outputs on I2C: enabled.
_RTCM_OUTPUTS_ON = [
    ("CFG_MSGOUT_RTCM_3X_TYPE1077_I2C", 1),  # GPS MSM7 every epoch
    ("CFG_MSGOUT_RTCM_3X_TYPE1097_I2C", 1),  # GAL MSM7 every epoch
    ("CFG_MSGOUT_RTCM_3X_TYPE1127_I2C", 1),  # BDS MSM7 every epoch
    ("CFG_MSGOUT_RTCM_3X_TYPE1005_I2C", 5),  # ARP every 5 epochs
    ("CFG_MSGOUT_RTCM_3X_TYPE1230_I2C", 5),  # GLO biases (will be empty for us)
]

# Measurement rate.  At 0.5 Hz (2000 ms) we have margin for AQ
# contention gaps; raise to 1 Hz only after smoke-test passes.
_RATE = [
    ("CFG_RATE_MEAS", 2000),  # ms between measurements (0.5 Hz)
    ("CFG_RATE_NAV", 1),       # 1 nav epoch per measurement
]

ALL_TARGET = _UBX_OUTPUTS_OFF + _RTCM_OUTPUTS_ON + _RATE


def open_port(device: str):
    """Open the F9T device.

    /dev/gnss* (kernel GNSS char device) is NOT a tty — pyserial's
    termios.tcgetattr fails on it.  Use the raw-fd wrapper.
    /dev/ttyACM*, /dev/gnss-top, etc. are real serial ports — use
    pyserial.
    """
    base = os.path.basename(device)
    if base.startswith("gnss") and base[4:].isdigit():
        return KernelGnssFd(device)
    # 38400 is a placeholder; the actual baud comes from the engine
    # config in production use.  For one-shot configuration this is
    # fine — VALSET works at any baud the F9T already negotiated.
    return serial.Serial(device, 38400, timeout=2)


def send_valset(
    s: serial.Serial,
    items: list[tuple[str, int]],
    *,
    layers: int = 0x07,  # RAM | BBR | FLASH
    dry_run: bool = False,
) -> bool:
    """Send a single CFG-VALSET with all items, wait for ACK."""
    msg = UBXMessage.config_set(layers, 0, items)
    payload_hex = msg.serialize().hex()
    print(f"VALSET layers=0x{layers:02x}  {len(items)} items:")
    for k, v in items:
        print(f"  {k} = {v}")
    print(f"  payload: {payload_hex[:100]}{'...' if len(payload_hex) > 100 else ''}")
    if dry_run:
        print("  (dry-run; not sent)")
        return True

    s.reset_input_buffer()
    s.write(msg.serialize())
    s.flush()

    deadline = time.monotonic() + 3.0
    rdr = UBXReader(s, protfilter=2)
    while time.monotonic() < deadline:
        try:
            raw, parsed = rdr.read()
        except Exception:
            continue
        if parsed is None:
            continue
        if parsed.identity == "ACK-ACK":
            print("  ACK")
            return True
        if parsed.identity == "ACK-NAK":
            print(f"  NAK on {parsed}")
            return False
    print("  timeout (no ACK/NAK in 3s)")
    return False


def poll_valget(
    s: serial.Serial,
    keys: list[str],
    *,
    layer: int = 0,  # 0 = RAM (running)
) -> dict[str, int | None]:
    """Poll current values of the named keys via CFG-VALGET."""
    out: dict[str, int | None] = {k: None for k in keys}
    msg = UBXMessage.config_poll(layer, 0, keys)
    s.reset_input_buffer()
    s.write(msg.serialize())
    s.flush()

    deadline = time.monotonic() + 3.0
    rdr = UBXReader(s, protfilter=2)
    while time.monotonic() < deadline:
        try:
            raw, parsed = rdr.read()
        except Exception:
            continue
        if parsed is None:
            continue
        if parsed.identity == "CFG-VALGET":
            for k in keys:
                if hasattr(parsed, k):
                    out[k] = getattr(parsed, k)
            return out
        if parsed.identity == "ACK-NAK":
            print(f"  WARN: NAK on VALGET {parsed}", file=sys.stderr)
            return out
    print("  timeout polling VALGET", file=sys.stderr)
    return out


def cmd_snapshot(s: serial.Serial, out: Path | None) -> int:
    keys = [k for k, _ in ALL_TARGET]
    snap = poll_valget(s, keys, layer=0)
    text = json.dumps(snap, indent=2, sort_keys=True)
    if out is None:
        print(text)
    else:
        out.write_text(text + "\n")
        print(f"snapshot written to {out}", file=sys.stderr)
    return 0


def cmd_apply(s: serial.Serial, *, dry_run: bool) -> int:
    print("==> Applying RTCM 3 output config to F9T")
    print("Step 1/4: disable UBX outputs on I2C")
    if not send_valset(s, _UBX_OUTPUTS_OFF, dry_run=dry_run):
        return 1
    print("Step 2/4: enable RTCM 3 MSM7 outputs on I2C")
    if not send_valset(s, _RTCM_OUTPUTS_ON, dry_run=dry_run):
        return 1
    print("Step 3/4: set measurement rate to 0.5 Hz")
    if not send_valset(s, _RATE, dry_run=dry_run):
        return 1
    print("Step 4/4: complete (config saved to RAM+BBR+FLASH per layers=0x07)")
    return 0


def cmd_revert(s: serial.Serial, snapshot_path: Path, *, dry_run: bool) -> int:
    snap = json.loads(snapshot_path.read_text())
    items = [(k, int(v)) for k, v in snap.items() if v is not None]
    if not items:
        print(f"snapshot {snapshot_path} has no usable values", file=sys.stderr)
        return 1
    print(f"==> Reverting {len(items)} keys from {snapshot_path}")
    if not send_valset(s, items, dry_run=dry_run):
        return 1
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    p.add_argument("device", help="F9T device, e.g. /dev/gnss0")
    p.add_argument("--dry-run", action="store_true",
                   help="show payloads without sending")
    p.add_argument("--snapshot-only", action="store_true",
                   help="poll current config, print, exit")
    p.add_argument("--snapshot-out", type=Path, default=None,
                   help="write snapshot to this file (otherwise stdout)")
    p.add_argument("--revert", type=Path, default=None,
                   help="restore config from a previous snapshot")
    args = p.parse_args()

    s = open_port(args.device)

    try:
        if args.revert is not None:
            return cmd_revert(s, args.revert, dry_run=args.dry_run)
        if args.snapshot_only:
            return cmd_snapshot(s, args.snapshot_out)
        # Default: snapshot first, then apply.
        if args.snapshot_out is not None:
            cmd_snapshot(s, args.snapshot_out)
        return cmd_apply(s, dry_run=args.dry_run)
    finally:
        s.close()


if __name__ == "__main__":
    sys.exit(main())
