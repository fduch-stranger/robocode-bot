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
- Gun pins/sets use global `ROBOCODE_GUN_MODE` / `ROBOCODE_GUN_SET` plus per-bot variants.
- Dynamic Cluster tuning hooks use per-bot `ROBOCODE_<BOT>_DYNAMIC_*`.
- `ROBOCODE_LEGACY_BOTS_ROOT` is optional and only for unported converted opponents.

Common commands:
```sh
scripts/run-battle.sh
scripts/run-battle.sh --rounds 1 bots/adaptive-prime bots/chase-lock
scripts/run-battle.sh --telemetry --rounds 24 bots/adaptive-prime bots/ports/basic-gf-surfer-port
scripts/run-ab.sh --name smoke --preset adaptive-1v1-core --rounds 1 --repeats 1
scripts/run-ab.sh --name surfer-port --preset adaptive-1v1-basic-gf-surfer-port --rounds 24 --repeats 3 --telemetry
```

Battle runner:
- `scripts/run-battle.sh` accepts Python bot directories and optional generic `--legacy <name>` opponents.
- `--run-dir <path>` writes a stable run directory.
- `--tick-sample N` logs sampled bot state for motion/stall inspection.
- `scripts/run-battle-series.sh` repeats battles and forwards unknown arguments.

Telemetry and analysis:
```sh
tools/telemetry_audit.py battle-results/runs/<run>/telemetry --require-bot adaptive-prime
tools/combat_economics_summary.py battle-results/runs/<run>
tools/gun_eval_summary.py battle-results/runs/<run>/telemetry --bot adaptive-prime
tools/radar_efficiency_summary.py battle-results/runs/<run>/telemetry --bot adaptive-prime
tools/intent_gap_summary.py battle-results/runs/<run>
tools/bot_motion_sanity.py battle-results/runs/<run-or-series> --bot <name>
```

Tool roles:
- `telemetry_audit.py`: JSONL readability, schema fields, bullet/gun attribution, and enemy-fire labels.
- `combat_economics_summary.py`: score, firsts, firepower, damage, and per-gun real conversion.
- `gun_eval_summary.py`: virtual-gun scores, selector diagnostics, and post-switch conversion.
- `radar_efficiency_summary.py`: radar/target freshness and reacquisition diagnostics.
- `intent_gap_summary.py`: missing or duplicate intent turns.
- `bot_motion_sanity.py`: sampled movement and stationary-span diagnostics.
- `DebugLogger.sample` throttles independently per event name and resets sampling windows each round.

Surfer policy:
- Use `bots/ports/basic-gf-surfer-port` and A/B preset `adaptive-1v1-basic-gf-surfer-port`.
- BasicGFSurfer-specific converted-Java aliases and presets were removed.
- Generic legacy support remains for unported references such as Diamond, DrussGT, and Saguaro.
- Accuracy filtering is optional diagnostic context for noisy converted bots; do not apply it to native Python ports.

A/B guidance:
- `1-8` rounds: smoke only.
- `12-16` rounds with repeats: exploration.
- `24 x 3`: normal promotion gate.
- Ask before spending `50+` rounds.
- Use A/B only with distinct baseline/candidate worktrees or refs.
- Use battle series when validating one current tree against a reference bot.

Telemetry viewer:
```sh
scripts/telemetry-ui.sh start
scripts/telemetry-ui.sh stop-all
scripts/telemetry-ui.sh disable
scripts/telemetry-ui.sh status
```

Keep telemetry off for performance A/B unless telemetry is required for the experiment.
