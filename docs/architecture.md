# Architecture

Why this is a separate repo, what lives where, what it depends on.

## Two-repo split

PePPAR-Fix is a precision-timing project.  Its engine, lab tooling,
peppar-mon visualization, and regression harness are all
PePPAR-Fix-internal concerns.  Adding BKG NTRIP Client (Qt5-heavy
GUI/CLI binary) and CNES PPP-Wizard (research-use-only C++ library)
as direct dependencies would:

1. Couple PePPAR-Fix's release engineering to BKG's Qt5 toolchain.
2. Bring in PPP-Wizard's non-OSI license to a project that is
   otherwise MIT-clean.
3. Make every PePPAR-Fix CI run depend on tools that 99% of
   PePPAR-Fix work doesn't touch.
4. Force every PePPAR-Fix contributor to understand the BNC
   integration even if they only care about the engine or the lab.

So the **only** PePPAR-Fix-side artifact is a documented JSONL
schema for solution logs (`docs/external-ppp-log-schema.md`) and a
generic stdlib-only overlay tool that consumes it
(`scripts/overlay/overlay_engine_solutions.py`).  Both are useful to
PePPAR-Fix regardless of whether BNC ever exists — anyone can write
an adapter for any PPP engine and overlay against PePPAR-Fix's own
output.

This repo (`peppar-bnc-glue`) owns:

- BNC and PPP-Wizard install scripts (apt-first, source-fallback).
- systemd units to run the daemons on a target host.
- Per-host configuration (BNC config, str2str command line, F9T
  RTCM 3 output config).
- The adapter that translates BNC's PPP solution log into the
  PePPAR-Fix external-PPP-log schema.

## Coupling minimization

| Concern | PePPAR-Fix repo | peppar-bnc-glue repo |
|---|---|---|
| Schema definition | `docs/external-ppp-log-schema.md` | reads it |
| Generic overlay tool | `scripts/overlay/` | — |
| BNC install / config | — | `deploy/`, `config/` |
| PPP-Wizard build | — | `deploy/build-ppp-wizard.sh` |
| systemd units | — | `deploy/systemd/` |
| F9T-as-RTCM TOML | — | `config/ptpmon-rtcm.toml` |
| BNC log → schema adapter | — | `adapters/bnc_log_to_peppar_schema.py` |
| Lab topology / gear | — (in `timelab/` repo, separate) | — |
| F9T config helpers (UBX-CFG-VALSET) | `scripts/peppar_fix/receiver.py` | copies what it needs (no submodule) |

The F9T config story is the only place where code might want to be
shared.  The pragmatic call: **copy** the small helpers we need on
day one.  If F9T config helpers ever grow into a real library
(see PePPAR-Fix's `scripts/configure_f9t.py` cross-rig note about
`bobvan/f9tLibs`), this repo refactors to depend on that.  Until
then, copies are fine — small files, easy to keep in sync by hand.

## Install policy: apt-first, source-fallback

Standing rule from the lab: prefer distro packages over source
builds wherever possible.  Concrete in `deploy/install-ptpmon.sh`:

| Tool | apt path | Fallback |
|---|---|---|
| Qt5 build deps | `qt5-qmake qtbase5-dev libqt5opengl5-dev` | n/a (required) |
| RTKLIB / `str2str` | `rtklib` (Debian/Ubuntu) | source build (Tomoji Takasu's repo) |
| BNC | varies by distro/release; check first | `deploy/build-bnc.sh` source build |
| PPP-Wizard | not in any distro | `deploy/build-ppp-wizard.sh` source build from ppp-wizard.net |
| Python deps for adapter | `apt install python3-numpy python3-pandas` if needed; otherwise venv | venv (preferred) |

**Python: always venv.**  Never `sudo pip install`, never
`--break-system-packages`.  PEP 668 enforcement on Debian/Ubuntu
makes system-pip installs corrupt distro Python.

## Why ptpmon

ptpmon is the launch host for three converging reasons (full
discussion in `project_to_main_bravo_charlie_intro_20260426.md`):

1. **L2-only F9T-PTP RF chain aligns with CNES phase biases.**  The
   F9T tracks GAL E1+E5b → L1C+L7Q natively, exactly what CNES
   publishes biases for.  No L5I/L5Q workaround.  The L5 fleet
   can't do that easily.
2. **i5-7600 + RAM** comfortably hosts Qt5 BNC + PPP-Wizard library.
   The L5-fleet Pis are tight.
3. **Single-purpose** role (PTP monitor + cross-engine PPP
   validator) is coherent with the hostname.

The plan is **dedicated** ptpmon — no concurrent peppar-fix engine
on this host.  That keeps the F9T's I2C bandwidth (1.5–1.7 kB/s
sustained, AQ-limited per `docs/platform-support.md` in
PePPAR-Fix) comfortable for a 1 Hz RTCM 3 MSM7 stream alone.

## Cross-repo coordination

PePPAR-Fix and peppar-bnc-glue evolve independently.  The schema
is the contract.  When the schema changes:

- PePPAR-Fix's schema doc bumps version (or a new file appears for
  v2).
- This repo's adapter is updated to emit the new version.
- The overlay tool in PePPAR-Fix continues reading both.

When PePPAR-Fix's F9T config conventions change:

- This repo's TOML is hand-updated to match.  No automated sync.

When BNC or PPP-Wizard upstream releases new versions:

- This repo's install scripts pin the version we know works.
- New version bring-up is a branch in this repo, not PePPAR-Fix's
  problem.

## What this repo will NOT do

- Replace the PePPAR-Fix engine.  This repo is a validator, not a
  production timing solution.
- Modify PePPAR-Fix's engine, wrapper, or peppar-mon.  Schema +
  overlay are the only PePPAR-Fix touchpoints.
- Take responsibility for PePPAR-Fix's lab hosts beyond ptpmon.
  Other hosts can run this repo's install if you want, but the
  repo's primary target is ptpmon.

## License

MIT (this repo's code).  Upstream tools have their own:

- BNC: GPL.
- PPP-Wizard: research use only (not OSI).  CNES distributes via
  ppp-wizard.net; we fetch and build, do not redistribute.
- RTKLIB / str2str: BSD-2.

The MIT license covers our scripts, configs, and the adapter — the
upstream tools are installed by the operator, not redistributed
by us.
