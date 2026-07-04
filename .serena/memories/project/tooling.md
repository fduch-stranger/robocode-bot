# Tooling And Commands

Setup:
```sh
cp .env.example .env
scripts/setup.sh
scripts/package.sh
```

Local config:
- `.env`, `.env.guns`, `battle-results/`, `dist/`, `.venv/`, and `legacy-bots/` are local/ignored.
- `PYTHON_BIN` controls venv creation; `ROBOCODE_PYTHON_BIN` controls bot/tool Python.
- `ROBOCODE_TELEMETRY_*` controls telemetry defaults.
- Gun pins/sets: global `ROBOCODE_GUN_MODE` / `ROBOCODE_GUN_SET`, plus per-bot `ROBOCODE_ADAPTIVE_*`, `ROBOCODE_CHASE_*`, `ROBOCODE_CIRCLE_*`, `ROBOCODE_SWEEP_*`.
- Dynamic-cluster experiment knobs are per bot: `ROBOCODE_ADAPTIVE_DYNAMIC_*`, `ROBOCODE_CHASE_DYNAMIC_*`, `ROBOCODE_CIRCLE_DYNAMIC_*`, `ROBOCODE_SWEEP_DYNAMIC_*`.
- `ROBOCODE_LEGACY_BOTS_ROOT` is optional and only for converted legacy parity/porting reference.

Common commands:
```sh
scripts/run-battle.sh
scripts/run-battle.sh --rounds 1 bots/adaptive-prime bots/chase-lock
scripts/run-battle.sh --telemetry --rounds 24 bots/adaptive-prime bots/ports/basic-gf-surfer-port
scripts/run-ab.sh --name smoke --preset adaptive-1v1-core --rounds 1 --repeats 1
scripts/run-ab.sh --name surfer-port --preset adaptive-1v1-basic-gf-surfer-port --rounds 24 --repeats 3 --telemetry
```

Telemetry and analysis:
```sh
tools/telemetry_audit.py battle-results/runs/<run>/telemetry --require-bot adaptive-prime
tools/combat_economics_summary.py battle-results/runs/<run>
tools/gun_eval_summary.py battle-results/runs/<run>/telemetry --bot adaptive-prime
```

Tool roles:
- `telemetry_audit.py`: JSONL readability, schema fields, bullet/gun attribution, enemy-fire labels.
- `combat_economics_summary.py`: raw score, firsts, firepower, damage, per-gun real conversion. Raw output is primary for local bots and ported opponents.
- `gun_eval_summary.py`: virtual-gun wave scores, selector diagnostics, post-switch real conversion, Traditional GF source diagnostics.

Surfer policy:
- Primary clean surfer target is `bots/ports/basic-gf-surfer-port`; A/B preset `adaptive-1v1-basic-gf-surfer-port`.
- Converted legacy `basic-gf-surfer` is parity/historical/porting reference only, not a normal quality gate.
- Accuracy filtering via `tools/combat_economics_summary.py --accuracy-filter-threshold 0.30` is optional legacy diagnostic context; do not apply it to the Python port.

A/B guidance:
- `1-8` rounds: smoke only.
- `12-16` rounds with repeats: exploration.
- `24 x 3`: normal promotion gate.
- Ask before spending `50+` rounds.
- Converted legacy opponents are not quality gates; port useful opponents into `bots/ports/` first.

Telemetry viewer:
```sh
scripts/telemetry-ui.sh start
scripts/telemetry-ui.sh stop-all
scripts/telemetry-ui.sh disable
scripts/telemetry-ui.sh status
```

Keep telemetry off for performance A/B unless telemetry is needed for the experiment. CLI `--telemetry` writes JSONL only unless `--telemetry-viewer` or `--telemetry-open` is passed.
