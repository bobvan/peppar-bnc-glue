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
# Verified against BNC 2.13.4 .ppp file output on ptpmon 2026-04-26.
# The PPP/logPath directory holds three useful files per run:
#
#   <STA>_<DOY>0000_01D_01S.ppp   — full per-epoch debug dump
#   <STA>_<DOY>0000_01D_01S.nmea  — NMEA GPGGA / GPRMC
#   bnc.log_<YYMMDD>              — general log, includes a less-rich
#                                    position line per epoch
#
# We parse the .ppp file because it carries the formal sigmas.  Per-
# epoch the .ppp has many lines of which we want the last one — the
# station summary:
#
#   2026-04-26_22:42:24.000 F9T_PTPMON
#       X = 157475.1067 +- 0.3586
#       Y = -4756187.9574 +- 0.5427
#       Z = 4232767.5092 +- 0.3704
#       dN = 0.9728 +- 0.2426
#       dE = -0.9187 +- 0.3512
#       dU = -1.6843 +- 0.6149
#
# All on one line in the file; fields order can have variable
# whitespace.  Date format uses underscore between date and time.
#
# BNC 2.13.4's float-PPP (no PPP-Wizard backend) does not emit a
# per-epoch fix-mode flag in the .ppp summary line — the AR status
# is observable only via the AMB diagnostic lines that precede the
# summary.  Map fix_mode = "float" until PPP-Wizard is in place
# (then per-SV "AMB lIF Exx FIXED" lines or a backend-specific flag
# appear).

_PPP_RE = re.compile(
    r"^\s*(?P<date>\d{4}-\d{2}-\d{2})_(?P<time>\d{2}:\d{2}:\d{2}(?:\.\d+)?)\s+"
    r"\S+\s+"  # station name
    r"X\s*=\s*(?P<x>[-+]?\d+\.\d+)\s+\+-\s+(?P<sx>\d+\.\d+)\s+"
    r"Y\s*=\s*(?P<y>[-+]?\d+\.\d+)\s+\+-\s+(?P<sy>\d+\.\d+)\s+"
    r"Z\s*=\s*(?P<z>[-+]?\d+\.\d+)\s+\+-\s+(?P<sz>\d+\.\d+)\s+"
    r"dN\s*=\s*(?P<dn>[-+]?\d+\.\d+)\s+\+-\s+(?P<sn>\d+\.\d+)\s+"
    r"dE\s*=\s*(?P<de>[-+]?\d+\.\d+)\s+\+-\s+(?P<se>\d+\.\d+)\s+"
    r"dU\s*=\s*(?P<du>[-+]?\d+\.\d+)\s+\+-\s+(?P<su>\d+\.\d+)"
)


def parse_line(line: str) -> dict | None:
    m = _PPP_RE.match(line)
    if not m:
        return None
    date = m.group("date")
    t = m.group("time")
    yr, mo, dy = (int(x) for x in date.split("-"))
    hh, mm, ss_str = t.split(":")
    sec = float(ss_str)
    dt = datetime(
        yr, mo, dy, int(hh), int(mm), int(sec),
        microsecond=int(round((sec - int(sec)) * 1e6)),
        tzinfo=timezone.utc,
    )
    return {
        "epoch_unix": dt.timestamp(),
        "ecef": (float(m.group("x")), float(m.group("y")), float(m.group("z"))),
        "ecef_sigma": (float(m.group("sx")), float(m.group("sy")), float(m.group("sz"))),
        "enu_residual": (float(m.group("de")), float(m.group("dn")), float(m.group("du"))),
        "enu_sigma": (float(m.group("se")), float(m.group("sn")), float(m.group("su"))),
    }


def emit_record(
    parsed: dict,
    *,
    engine: str,
    corrections_source: str,
    host: str | None,
) -> dict:
    # BNC 2.13.4 float-PPP doesn't emit a per-epoch fix-mode flag in
    # the .ppp summary line.  Hard-code "float" for now; revisit when
    # PPP-Wizard backend is in place (CNES distributes by request —
    # see deploy/build-ppp-wizard.sh).
    rec = {
        "epoch_unix": parsed["epoch_unix"],
        "engine": engine,
        "corrections_source": corrections_source,
        "fix_mode": "float",
        "pos": {"ecef": list(parsed["ecef"])},
        "sigma": {
            "e": parsed["enu_sigma"][0],
            "n": parsed["enu_sigma"][1],
            "u": parsed["enu_sigma"][2],
        },
    }
    if host:
        rec["host"] = host
    # Engine-private: BNC's per-axis ECEF sigmas + dN/dE/dU residuals
    # against the a-priori.
    rec["_bnc_ecef_sigma"] = list(parsed["ecef_sigma"])
    rec["_bnc_enu_residual"] = list(parsed["enu_residual"])
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
