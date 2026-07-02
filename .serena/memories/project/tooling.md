# Tooling And Commands

Local setup:
```sh
cp .env.example .env
scripts/setup.sh
scripts/package.sh
```

Important local config:
- `.env` is private and ignored by git.
- `PYTHON_BIN` controls venv creation.
- `ROBOCODE_PYTHON_BIN` overrides bot launcher/telemetry Python.
- `ROBOCODE_LEGACY_BOTS_ROOT` points to converted legacy bots. If empty, scripts use ignored repo-local `legacy-bots/`.
- Telemetry defaults are controlled by `ROBOCODE_TELEMETRY_*` variables.
- Adaptive gun testing env vars include `ROBOCODE_ADAPTIVE_GUN_MODE`, `ROBOCODE_ADAPTIVE_GUN_EVAL`, and `ROBOCODE_ADAPTIVE_GUN_EVAL_INTERVAL`.

Battle/tool commands:
- Default battle with all local bots: `scripts/run-battle.sh`.
- Short 1v1 smoke: `scripts/run-battle.sh --rounds 1 bots/adaptive-prime bots/chase-lock`.
- Telemetry JSONL without viewer: `scripts/run-battle.sh --telemetry bots/adaptive-prime bots/chase-lock`.
- Telemetry with viewer daemon: `scripts/run-battle.sh --telemetry --telemetry-viewer bots/adaptive-prime bots/chase-lock`.
- Telemetry with opened viewer: `scripts/run-battle.sh --telemetry --telemetry-open bots/adaptive-prime bots/chase-lock`.
- A/B smoke: `scripts/run-ab.sh --name smoke --preset adaptive-1v1-core --rounds 1 --repeats 1`.
- Legacy discovery when configured: `scripts/run-battle.sh --list-legacy`.
- Active legacy boss aliases: `drussgt`, `saguaro`, `basic-gf-surfer`, `diamond`.
- Telemetry viewer commands: `scripts/telemetry-ui.sh start|stop|stop-all|disable|status`.
- Telemetry audit: `tools/telemetry_audit.py battle-results/runs/<run>/telemetry --require-bot adaptive-prime`.
- Gun/eval summary: `tools/gun_eval_summary.py battle-results/runs/<run>/telemetry --bot adaptive-prime`.

A/B round guidance:
- `1-8` rounds are smoke checks only: crashes, packaging, telemetry shape, and obvious churn/regression signals.
- `12-16` rounds with `2` repeats is the exploratory A/B tier while searching for candidate thresholds.
- `24` rounds with `3` repeats is the promotion gate before treating tuning as broadly enabled.
- `50-100+` rounds on key matchups is an optional expensive confirmation tier for high-risk or near-merge changes; get user confirmation first.
- Boss-bot checks should be repeated; one short legacy run is not representative.

Keep telemetry off for performance A/B benchmarks unless debugging telemetry itself. CLI `--telemetry` writes JSONL only by default; viewer startup requires explicit `--telemetry-viewer` or `--telemetry-open`. CLI runs write artifacts under `battle-results/runs/<timestamp>/`; A/B runs under `battle-results/ab/<timestamp>-<name>/`.

Legacy boss notes:
- `basic-gf-surfer` is currently the most useful efficient surfer check.
- `diamond` can be contaminated by legacy-side file-write/NPE issues in this environment; treat Diamond results as weak unless the legacy setup is fixed.