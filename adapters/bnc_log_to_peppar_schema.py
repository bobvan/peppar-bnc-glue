#!/usr/bin/env python3
"""Adapter: BNC PPP solution log → PePPAR-Fix external-PPP-log JSONL.

Reads BNC's per-epoch PPP output (text format produced when
PPP/logFile is enabled in bnc.conf) and emits the PePPAR-Fix
external-PPP-log schema documented at
https://github.com/bobvan/PePPAR-Fix/blob/main/docs/external-ppp-log-schema.md

Usage:
    bnc_log_to_peppar_schema.py \\
        --in /var/log/bnc/ppp-ptpmon.txt \\
        --out /var/log/bnc/ppp-ptpmon.jsonl \\
        --engine bnc-ppp-wizard \\
        --corrections-source "PPP-Wizard_BNC_SSRA00CNE0" \\
        --host ptpmon

Two modes:
- One-shot: read a complete log and convert.
- Tail mode (--follow): tail -f the BNC log file and emit each new
  epoch immediately (useful for live overlay against the PePPAR-Fix
  engine's [AntPosEst]).

Stdlib only.  Runs in the repo's venv but doesn't actually need
non-stdlib deps — pyproject placeholder for future tightening.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# ── BNC PPP log format reference ─────────────────────────────────────────── #
#
# TODO(charlie 2026-04-26): the exact format depends on the BNC
# version and PPP backend.  When BNC's PPP/logFile is enabled, each
# converged epoch produces a line like:
#
#   YYYY-MM-DD HH:MM:SS X Y Z DX DY DZ NSat AmbFix [other]
#
# where (X Y Z) is ECEF in meters, (DX DY DZ) is the residual
# against the a-priori, NSat is satellite count, AmbFix is "F" / "f" /
# blank for fix status.  This will need verification on first
# successful BNC startup on ptpmon — sample a real file and confirm
# the columns before this parser ships.
#
# The placeholder regex below assumes the columnar form above.

_LOG_RE = re.compile(
    r"^\s*(\d{4})-(\d{2})-(\d{2})\s+(\d{2}):(\d{2}):(\d{2}(?:\.\d+)?)\s+"
    r"(?P<x>[-+]?\d+\.\d+)\s+(?P<y>[-+]?\d+\.\d+)\s+(?P<z>[-+]?\d+\.\d+)\s+"
    r"(?P<dx>[-+]?\d+\.\d+)\s+(?P<dy>[-+]?\d+\.\d+)\s+(?P<dz>[-+]?\d+\.\d+)\s+"
    r"(?P<n>\d+)\s+"
    r"(?P<fix>[Ff]|-)?"
)


def parse_line(line: str) -> dict | None:
    m = _LOG_RE.match(line)
    if not m:
        return None
    yr, mo, dy, hh, mm, ss = m.group(1, 2, 3, 4, 5, 6)
    sec = float(ss)
    dt = datetime(
        int(yr), int(mo), int(dy), int(hh), int(mm), int(sec),
        microsecond=int(round((sec - int(sec)) * 1e6)),
        tzinfo=timezone.utc,
    )
    return {
        "epoch_unix": dt.timestamp(),
        "ecef": (float(m.group("x")), float(m.group("y")), float(m.group("z"))),
        "residual_ecef": (
            float(m.group("dx")),
            float(m.group("dy")),
            float(m.group("dz")),
        ),
        "n_used": int(m.group("n")),
        "fix_raw": m.group("fix"),
    }


def map_fix_mode(bnc_fix: str | None) -> str:
    """Map BNC's per-epoch AR indicator onto SvAmbState lifecycle vocab."""
    # TODO(charlie 2026-04-26): BNC + PPP-Wizard exposes the AR ratio
    # test result via a separate channel from the position log; the
    # log's per-epoch flag (F/f/-) is coarser than our 5-state enum.
    # Map conservatively until we have the full BNC API plumbing:
    if bnc_fix == "F":
        return "validated"
    if bnc_fix == "f":
        return "nl_fixed"
    return "float"


def emit_record(
    parsed: dict,
    *,
    engine: str,
    corrections_source: str,
    host: str | None,
) -> dict:
    rec = {
        "epoch_unix": parsed["epoch_unix"],
        "engine": engine,
        "corrections_source": corrections_source,
        "fix_mode": map_fix_mode(parsed.get("fix_raw")),
        "pos": {"ecef": list(parsed["ecef"])},
        "n_used": parsed["n_used"],
    }
    if host:
        rec["host"] = host
    # Engine-private: BNC's residual against its a-priori.
    rec["_bnc_residual_ecef"] = list(parsed["residual_ecef"])
    return rec


def run_oneshot(
    in_path: Path,
    out_path: Path,
    *,
    engine: str,
    corrections_source: str,
    host: str | None,
) -> int:
    n = 0
    with in_path.open("r", encoding="utf-8") as fin, out_path.open(
        "w", encoding="utf-8"
    ) as fout:
        fout.write(
            f"# schema-version: 1\n"
            f"# adapter: bnc_log_to_peppar_schema.py from peppar-bnc-glue\n"
            f"# generated: {datetime.now(timezone.utc).isoformat()}\n"
        )
        for line in fin:
            parsed = parse_line(line)
            if parsed is None:
                continue
            rec = emit_record(
                parsed,
                engine=engine,
                corrections_source=corrections_source,
                host=host,
            )
            fout.write(json.dumps(rec) + "\n")
            n += 1
    return n


def run_follow(
    in_path: Path,
    out_path: Path,
    *,
    engine: str,
    corrections_source: str,
    host: str | None,
) -> None:
    with in_path.open("r", encoding="utf-8") as fin, out_path.open(
        "a", encoding="utf-8"
    ) as fout:
        fin.seek(0, 2)  # to end
        while True:
            line = fin.readline()
            if not line:
                time.sleep(0.5)
                continue
            parsed = parse_line(line)
            if parsed is None:
                continue
            rec = emit_record(
                parsed,
                engine=engine,
                corrections_source=corrections_source,
                host=host,
            )
            fout.write(json.dumps(rec) + "\n")
            fout.flush()


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    p.add_argument("--in", dest="in_path", type=Path, required=True)
    p.add_argument("--out", dest="out_path", type=Path, required=True)
    p.add_argument("--engine", default="bnc-ppp-wizard")
    p.add_argument(
        "--corrections-source",
        default="PPP-Wizard_BNC_SSRA00CNE0",
        help="free-text identifier for the corrections-source axis "
        "(see PePPAR-Fix's external-PPP-log-schema.md)",
    )
    p.add_argument("--host", default=None)
    p.add_argument(
        "--follow",
        action="store_true",
        help="tail -f mode for live overlay",
    )
    args = p.parse_args()

    if args.follow:
        run_follow(
            args.in_path,
            args.out_path,
            engine=args.engine,
            corrections_source=args.corrections_source,
            host=args.host,
        )
        return 0

    n = run_oneshot(
        args.in_path,
        args.out_path,
        engine=args.engine,
        corrections_source=args.corrections_source,
        host=args.host,
    )
    print(f"wrote {n} records to {args.out_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
