# Tooling And Commands

Local setup:
```sh
cp .env.example .env
scripts/setup.sh
scripts/package.sh
scripts/run-battle.sh
```

Important local config:
- `.env` is private and ignored by git.
- `PYTHON_BIN` controls venv creation.
- `ROBOCODE_PYTHON_BIN` overrides bot launcher/telemetry Python.
- `ROBOCODE_LEGACY_BOTS_ROOT` points to converted legacy bots. If empty, scripts use ignored repo-local `legacy-bots/`.
- Telemetry defaults are controlled by `ROBOCODE_TELEMETRY_*` variables.
- Adaptive gun testing env vars include `ROBOCODE_ADAPTIVE_GUN_MODE`, `ROBOCODE_ADAPTIVE_GUN_EVAL`, and `ROBOCODE_ADAPTIVE_GUN_EVAL_INTERVAL`.

Battle/tool commands:
- Package GUI-ready bot zips: `scripts/package.sh`.
- Default battle with all local bots: `scripts/run-battle.sh`.
- Short 1v1 smoke: `scripts/run-battle.sh --rounds 1 bots/adaptive-prime bots/chase-lock`.
- Telemetry JSONL without viewer: `scripts/run-battle.sh --telemetry bots/adaptive-prime bots/chase-lock`.
- Telemetry with viewer daemon: `scripts/run-battle.sh --telemetry --telemetry-viewer bots/adaptive-prime bots/chase-lock`.
- Telemetry with opened viewer: `scripts/run-battle.sh --telemetry --telemetry-open bots/adaptive-prime bots/chase-lock`.
- A/B smoke: `scripts/run-ab.sh --name smoke --preset adaptive-1v1-core --rounds 1 --repeats 1`.
- Legacy discovery when configured: `scripts/run-battle.sh --list-legacy`.
- Legacy boss smoke when configured: `scripts/run-battle.sh --rounds 1 bots/adaptive-prime --legacy saguaro`.
- Active legacy boss aliases: `drussgt`, `saguaro`, `basic-gf-surfer`, `diamond`.
- Legacy A/B boss smoke when configured: `scripts/run-ab.sh --name boss-smoke --preset adaptive-1v1-boss --rounds 1 --repeats 1`.
- Telemetry viewer commands: `scripts/telemetry-ui.sh start|stop|stop-all|disable|status`.
- Telemetry audit: `tools/telemetry_audit.py battle-results/runs/<run>/telemetry --require-bot adaptive-prime`.
- Gun/eval summary: `tools/gun_eval_summary.py battle-results/runs/<run>/telemetry --bot adaptive-prime`.

Keep telemetry off for performance A/B benchmarks unless debugging telemetry itself. CLI `--telemetry` writes JSONL only by default; viewer startup requires explicit `--telemetry-viewer` or `--telemetry-open`. CLI runs write artifacts under `battle-results/runs/<timestamp>/`; A/B runs under `battle-results/ab/<timestamp>-<name>/`.

Legacy boss notes:
- `basic-gf-surfer` is currently the most useful efficient surfer check.
- `diamond` can be contaminated by legacy-side file-write/NPE issues in this environment; treat Diamond results as weak unless the legacy setup is fixed.