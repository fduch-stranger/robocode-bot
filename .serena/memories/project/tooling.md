# Tooling And Commands

Local setup:
```sh
cp .env.example .env
scripts/setup.sh
scripts/package.sh
```

Important local config:
- `.env` is private and ignored by git.
- `.env.guns` is private and ignored by git; copy `.env.guns.example` for GUI/debug gun pins and selectable-set overrides. It loads after `.env`, while already-exported process variables still win; empty assignments clear matching `.env` gun settings. With no overrides enabled, bots have no pinned gun and the live set is `linear`, `traditional_gf`, `dynamic_cluster`, `displacement`; all standard wired guns remain pinnable. Source-tree runs read it from the repo root; packaged GUI runs read it from the package/extraction root beside the bot directories via `bot_core/launcher_env.sh`. Some guns need target history before they return an aim bearing, so real battles can show a short startup fallback before a pinned/narrowed mode becomes active.
- `PYTHON_BIN` controls venv creation.
- `ROBOCODE_PYTHON_BIN` overrides bot launcher/telemetry Python.
- `ROBOCODE_LEGACY_BOTS_ROOT` points to converted legacy bots. If empty, scripts use ignored repo-local `legacy-bots/`.
- `ROBOCODE_LEGACY_JAVA11_BIN` can override the Java 11 executable used by the CLI legacy-bot shim; by default it prefers the Homebrew OpenJDK 11 path when present so converted legacy bots avoid newer-JDK final-field mutation warnings.
- Telemetry defaults are controlled by `ROBOCODE_TELEMETRY_*` variables.
- Gun testing env vars include per-bot gun-mode/eval prefixes such as `ROBOCODE_ADAPTIVE_GUN_MODE`, `ROBOCODE_CHASE_GUN_EVAL`, and matching `_GUN_EVAL_INTERVAL` vars. Dynamic-cluster experiment knobs are also per-bot: `ROBOCODE_ADAPTIVE_DYNAMIC_*`, `ROBOCODE_CHASE_DYNAMIC_*`, `ROBOCODE_CIRCLE_DYNAMIC_*`, and `ROBOCODE_SWEEP_DYNAMIC_*`.

Battle/tool commands:
- Default battle with all local bots: `scripts/run-battle.sh`.
- Short 1v1 smoke: `scripts/run-battle.sh --rounds 1 bots/adaptive-prime bots/chase-lock`.
- Telemetry JSONL without viewer: `scripts/run-battle.sh --telemetry bots/adaptive-prime bots/chase-lock`.
- Telemetry with viewer daemon: `scripts/run-battle.sh --telemetry --telemetry-viewer bots/adaptive-prime bots/chase-lock`.
- Telemetry with opened viewer: `scripts/run-battle.sh --telemetry --telemetry-open bots/adaptive-prime bots/chase-lock`.
- A/B smoke: `scripts/run-ab.sh --name smoke --preset adaptive-1v1-core --rounds 1 --repeats 1`.
- Python surfer-port smoke: `scripts/run-ab.sh --name surfer-port-smoke --preset adaptive-1v1-basic-gf-surfer-port --rounds 1 --repeats 1`.
- Legacy discovery when configured: `scripts/run-battle.sh --list-legacy`.
- Known converted legacy aliases include `drussgt`, `saguaro`, `basic-gf-surfer`, `basic-gf-surfer-original`, and `diamond`; use them for parity, historical comparison, or porting reference, not as quality gates.
- `basic-gf-surfer` prefers `wiki.BasicGFSurferFixed_1.02` when present and falls back to `wiki.BasicGFSurfer_1.02`; use `basic-gf-surfer-original` or `legacy:wiki.BasicGFSurfer_1.02` for the unpatched converted bot.
- Native Python surfer benchmark: `bots/ports/basic-gf-surfer-port`; A/B preset `adaptive-1v1-basic-gf-surfer-port`. This is the primary clean surfer target for repeatable tuning. Converted legacy `basic-gf-surfer` remains for parity, historical comparison, and porting reference only; do not treat it as the normal promotion gate.
- Telemetry viewer commands: `scripts/telemetry-ui.sh start|stop|stop-all|disable|status`.
- Telemetry viewer selected-bot metrics show current gun, live-selectable guns, and pinned gun from startup `bot.config` telemetry; raw `bot.config` records still include force-testable guns.
- Telemetry viewer generations reset on `telemetry.session` for new processes/files and on bot-emitted `battle.reset` for same-process GUI game restarts; normal `round.reset` remains within the same generation unless it looks like an aborted/reset GUI run.
- Telemetry audit: `tools/telemetry_audit.py battle-results/runs/<run>/telemetry --require-bot adaptive-prime`.
- Gun/eval summary: `tools/gun_eval_summary.py battle-results/runs/<run>/telemetry --bot adaptive-prime`.
- Combat economics analysis: `tools/combat_economics_summary.py battle-results/runs/<run>` reports raw score, firsts, firepower, damage, and per-gun real conversion. It replaces the old surfer-specific glitch analyzer. Accuracy filtering is optional legacy diagnostic context via `--accuracy-filter-threshold 0.30`; do not apply it to `bots/ports/basic-gf-surfer-port`.
- Focused surfer A/B: `scripts/run-ab.sh --preset adaptive-1v1-basic-gf-surfer-port --rounds 24 --repeats 3 --telemetry`, with repeatable `--baseline-env KEY=VALUE` / `--candidate-env KEY=VALUE` for forced-gun and tuning sweeps.

A/B round guidance:
- `1-8` rounds are smoke checks only: crashes, packaging, telemetry shape, and obvious churn/regression signals.
- `12-16` rounds with `2` repeats is the exploratory A/B tier while searching for candidate thresholds.
- `24` rounds with `3` repeats is the promotion gate before treating tuning as broadly enabled.
- `50-100+` rounds on key matchups is an optional expensive confirmation tier for high-risk or near-merge changes; get user confirmation first.
- Converted legacy opponents are not quality gates; port useful opponents into `bots/ports/` before treating them as tuning targets.

Keep telemetry off for performance A/B benchmarks unless debugging telemetry itself. CLI `--telemetry` writes JSONL only by default; viewer startup requires explicit `--telemetry-viewer` or `--telemetry-open`. CLI runs write artifacts under `battle-results/runs/<timestamp>/`; A/B runs under `battle-results/ab/<timestamp>-<name>/`.

Legacy notes:
- Converted legacy bots are retained for parity, historical comparison, and porting work.
- `basic-gf-surfer` may map to the fixed converted variant when configured, but the Python port is the normal repeatable surfer benchmark.
- `diamond` can be contaminated by legacy-side file-write/NPE issues in this environment; treat Diamond results as weak unless the legacy setup is fixed or ported.
