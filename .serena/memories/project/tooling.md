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

Battle/tool commands:
- Package GUI-ready bot zips: `scripts/package.sh`.
- Default battle with all local bots: `scripts/run-battle.sh`.
- Short 1v1 smoke: `scripts/run-battle.sh --rounds 1 bots/adaptive-prime bots/chase-lock`.
- A/B smoke: `scripts/run-ab.sh --name smoke --preset adaptive-1v1-core --rounds 1 --repeats 1`.
- Legacy discovery when configured: `scripts/run-battle.sh --list-legacy`.
- Legacy boss smoke when configured: `scripts/run-battle.sh --rounds 1 bots/adaptive-prime --legacy basic-gf-surfer`.
- Additional legacy boss aliases: `hawk-on-fire`, `diamond`.
- Legacy A/B boss smoke when configured: `scripts/run-ab.sh --name boss-smoke --preset adaptive-1v1-boss --rounds 1 --repeats 1`.
- Telemetry viewer commands: `scripts/telemetry-ui.sh start|stop|stop-all|disable|status`.
- Telemetry audit: `tools/telemetry_audit.py battle-results/runs/<run>/telemetry --require-bot adaptive-prime`.

Keep telemetry off for performance A/B benchmarks unless debugging telemetry itself. CLI runs write artifacts under `battle-results/runs/<timestamp>/`; A/B runs under `battle-results/ab/<timestamp>-<name>/`.