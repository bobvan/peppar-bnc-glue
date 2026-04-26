# peppar-bnc-glue

BKG NTRIP Client (BNC) + CNES PPP-Wizard installation, deployment,
and integration glue for the PePPAR-Fix lab.  Sits **alongside**
PePPAR-Fix without modifying it — only the **schema** of the
solution log they exchange is defined in PePPAR-Fix
(`docs/external-ppp-log-schema.md`).

## What this repo does

Stand up a **live cross-engine PPP-AR validator** on a host with a
u-blox ZED-F9T.  The validator runs entirely independently of the
PePPAR-Fix engine — same antenna, same NTRIP corrections, different
algorithm — and emits its solution in the documented external-PPP-
log schema so PePPAR-Fix's `scripts/overlay/` can compare it
against the engine's `[AntPosEst]` output epoch-by-epoch.

The point is to answer:

> Does an independent real-time PPP-AR engine, fed the same RTCM
> SSR streams as PePPAR-Fix, produce the same position?  If not,
> the gap is engine.  If yes within mm, the gap is shared
> site/SSR/atmosphere noise.

This bears directly on the streaming-EKF-floor architecture
question
(`memory/project_to_charlie_ptpmon_greenlight_20260426.md`).

## Architecture

```
F9T (USB or kernel I2C) ──► str2str ──► local NTRIP mount
                                              │
       NTRIP caster (CNES SSRA00CNE0) ──► BNC ◄┘
                                              │
                                              ▼  rtrover API
                                     PPP-Wizard library
                                              │
                                              ▼  BNC PPP log
                                       adapters/bnc_log_to_peppar_schema.py
                                              │
                                              ▼  external-PPP-log JSONL
                                       PePPAR-Fix scripts/overlay/
```

PePPAR-Fix doesn't know this repo exists.  This repo's only
PePPAR-Fix-side dependency is the JSONL **schema** documented in
`docs/external-ppp-log-schema.md` of that repo.

## Repo layout

```
peppar-bnc-glue/
├── README.md                               this file
├── LICENSE                                 MIT (matches PePPAR-Fix)
├── docs/
│   └── architecture.md                     design rationale + repo split
├── deploy/
│   ├── install-ptpmon.sh                   apt-first install on ptpmon
│   ├── build-bnc.sh                        source-build BNC if no apt pkg
│   ├── build-ppp-wizard.sh                 source-build PPP-Wizard
│   └── systemd/
│       ├── str2str-ptpmon.service          F9T → local NTRIP mount
│       └── bnc-ptpmon.service              BNC headless w/ PPP-Wizard
├── config/
│   ├── bnc.conf.example                    BNC headless template
│   ├── ptpmon-rtcm.toml                    F9T configured for RTCM 3 output
│   └── str2str.args.example                str2str command line template
├── adapters/
│   └── bnc_log_to_peppar_schema.py         BNC PPP log → JSONL schema
├── tests/
└── venv/                                   gitignored; create per host
```

## Install (ptpmon)

```bash
# Clone:
ssh ptpmon
git clone bob@gt:git/peppar-bnc-glue.git ~/peppar-bnc-glue
cd ~/peppar-bnc-glue

# Run install:
sudo apt update
./deploy/install-ptpmon.sh

# Per-host config:
cp config/bnc.conf.example config/bnc.conf
# edit credentials etc.

# Activate venv (for adapter), install adapter deps:
python3 -m venv venv
venv/bin/pip install -r adapters/requirements.txt

# Configure F9T for RTCM 3 output (drops RAWX/TIM-TP/SFRBX):
./deploy/configure-f9t-rtcm.sh

# Start services:
sudo systemctl start str2str-ptpmon
sudo systemctl start bnc-ptpmon
```

**Python policy**: never `sudo pip install` or
`pip install --break-system-packages` — always venv per-host.
Standing rule from the lab; PEP 668 enforcement on Debian/Ubuntu
makes system-pip installs corrupt distro Python.

## Hardware target

- **Primary**: ptpmon (i5-7600 + E810 + ZED-F9T-PTP, TIM 2.20,
  L2-only RF chain; F9T on `/dev/gnss0` via E810 AQ-mediated I2C).
  See `config/ptpmon-rtcm.toml` for the F9T configuration.
- **Future**: any host with a ZED-F9T — port the per-host config
  TOML and the install script.

## Why ptpmon specifically

- L2-only RF chain happens to align with CNES phase biases
  (GAL E1+E5b → L1C+L7Q is exactly what CNES publishes).  No
  L5I/L5Q workaround needed.  See PePPAR-Fix's
  `project_cnes_phase_bias_signals` memory.
- x86 i5-7600 has CPU + RAM headroom for Qt5 BNC + PPP-Wizard
  library, unlike the L5-fleet Pi-class hosts.
- Single-purpose role (PTP monitor + cross-engine validator)
  matches the hostname's intent.

## Status

**Initial bootstrap.**  Schema + skeleton scaffold landing.  Lab
work begins after install script + F9T config TOML are validated
on ptpmon.

## License

MIT — see `LICENSE`.

PePPAR-Fix is also MIT.  Note that **PPP-Wizard itself is not
OSI-licensed** — CNES distributes it for non-commercial research
use only.  `deploy/build-ppp-wizard.sh` fetches PPP-Wizard from
ppp-wizard.net.  This repo's MIT license covers our glue code, not
the upstream BNC (GPL) or PPP-Wizard (research use) binaries it
installs.
