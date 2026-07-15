# Tooling

This page is the compact command reference for setup, battles, telemetry, A/B
runs, and converted legacy checks. Prefer `--help` on the scripts for complete
option lists.

## Setup

```sh
cp .env.example .env
scripts/setup.sh
scripts/package.sh
```

Important local variables:

| Variable | Purpose |
| --- | --- |
| `PYTHON_BIN` | Python used by `scripts/setup.sh`. |
| `ROBOCODE_PYTHON_BIN` | Python used by bot launchers and tooling. |
| `ROBOCODE_TELEMETRY_DIR` | Default GUI telemetry JSONL directory. |
| `ROBOCODE_TELEMETRY_HOST` / `ROBOCODE_TELEMETRY_PORT` | Telemetry viewer bind address. |
| `ROBOCODE_GUN_MODE` | Pin all bots to a standard gun where supported. |
| `ROBOCODE_GUN_SET` | Comma-separated selectable gun set. |
| `ROBOCODE_<BOT>_GUN_MODE` / `ROBOCODE_<BOT>_GUN_SET` | Per-bot gun pins and gun sets. |
| `ROBOCODE_LEGACY_BOTS_ROOT` | Optional converted legacy bot root. |

Standard force-testable guns are `head_on`, `linear`, `linear_wall_aware`,
`displacement`, `traditional_gf`, `dynamic_cluster`, and `anti_surfer`.

## Battles

Main wrapper:

```sh
scripts/run-battle.sh [options] [bot-dir...]
```

Common runs:

```sh
scripts/run-battle.sh
scripts/run-battle.sh --rounds 1 bots/adaptive-prime bots/chase-lock
scripts/run-battle.sh --rounds 24 bots/adaptive-prime bots/ports/basic-gf-surfer-port
scripts/run-battle.sh --telemetry --rounds 24 bots/adaptive-prime bots/ports/basic-gf-surfer-port
```

Common options:

| Option | Purpose |
| --- | --- |
| `--rounds N` | Number of rounds. |
| `--run-dir DIR` | Output directory. |
| `--debug` | Bot text decision logs. |
| `--telemetry` | Write telemetry JSONL. |
| `--telemetry-viewer` / `--telemetry-open` | Start, optionally open, the viewer. |
| `--record` | Write `.battle.gz` recordings. |
| `--intent-diagnostics` | Capture intent diagnostics. |
| `--tick-sample N` | Sample runner ticks. |
| `--legacy NAME|all` | Add converted legacy bots for porting/reference checks. |
| `--legacy-root DIR` | Override converted legacy root. |
| `--list-legacy` | Print known converted legacy aliases. |

Run artifacts live under `battle-results/runs/<timestamp>/`:

- `results.json`: final scores.
- `runner.log`: runner lifecycle and sampled tick data.
- `process.log`: raw Robocode runner/server/booter output.
- `debug/`, `telemetry/`, `recordings/`, `intents.jsonl`: optional outputs.

## Telemetry

CLI telemetry:

```sh
scripts/run-battle.sh --telemetry bots/adaptive-prime bots/chase-lock
scripts/run-battle.sh --telemetry --telemetry-open bots/adaptive-prime bots/chase-lock
```

GUI telemetry viewer:

```sh
scripts/telemetry-ui.sh start
scripts/telemetry-ui.sh list
scripts/telemetry-ui.sh stop-all
scripts/telemetry-ui.sh disable
scripts/telemetry-ui.sh status
```

`stop-all` stops viewer processes. `disable` prevents GUI-launched bots from
starting new viewers.

The event contract is generated from code:

```sh
tools/telemetry_schema_docs.py --output docs/telemetry-schema.md
```

## Experiment Analysis

Use this pipeline for telemetry-backed tuning runs:

```sh
tools/telemetry_audit.py battle-results/runs/<run>/telemetry \
  --require-bot adaptive-prime \
  --json-output battle-results/runs/<run>/telemetry-audit.json

tools/combat_economics_summary.py battle-results/runs/<run> \
  --json-output battle-results/runs/<run>/combat-economics-summary.json

tools/gun_eval_summary.py battle-results/runs/<run>/telemetry \
  --bot adaptive-prime \
  --json-output battle-results/runs/<run>/gun-eval-summary.json

tools/fire_utility_summary.py battle-results/runs/<run>/telemetry \
  --bot adaptive-prime \
  --json-output battle-results/runs/<run>/fire-utility-summary.json

tools/fire_utility_replay.py \
  battle-results/runs/<run-a>/telemetry \
  battle-results/runs/<run-b>/telemetry \
  --bot adaptive-prime \
  --json-output battle-results/fire-utility-replay.json

tools/radar_efficiency_summary.py battle-results/runs/<run>/telemetry \
  --bot adaptive-prime \
  --json-output battle-results/runs/<run>/radar-efficiency-summary.json

tools/intent_gap_summary.py battle-results/runs/<run> \
  --json-output battle-results/runs/<run>/intent-gap-summary.json
```

Tool roles:

- `telemetry_audit.py`: JSONL readability, required bots, schema fields,
  bullet/gun attribution, enemy-fire evasion labels, movement-evidence
  separation, and fire-utility formulas/lifecycle.
- `combat_economics_summary.py`: raw score, firsts, firepower, damage, and
  per-gun real conversion. Raw output is the primary view for local bots and
  ported opponents.
- `gun_eval_summary.py`: virtual-gun wave scores, selected-gun diagnostics,
  post-switch real conversion, and Traditional GF source diagnostics.
- `fire_utility_summary.py`: causal accepted-shot probability reliability by
  probability, range, power, mode, quality, fallback, and chronological window,
  plus ready-gun fire/hold reasons. Calibration diagnostics include
  supported-shot coverage, expected calibration error, Brier skill against the
  fixed `Beta(1,5)` prior, and hit/miss probability separation.
- `fire_utility_replay.py`: reruns the current production shadow calibrator over
  one or more historical telemetry directories. It preserves staged ready-fire
  snapshots across delayed accepted callbacks, reconciles durable hits before
  closing unresolved round-end shots, resets learning independently per run,
  and reports both per-run and aggregate reliability. Use it for
  reproducible retrospective candidate checks; it does not replace a fresh
  prequential validation run.
- `radar_efficiency_summary.py`: target freshness, radar mode distribution,
  stale/lost shots, hit rate by target age, reacquire/drop counts, and
  enemy-fire scan-gap diagnostics.
- `intent_gap_summary.py`: missing or duplicate intent turns from
  `--intent-diagnostics` runs. Use it with `bot.turn_timing` and
  `bot.skipped_turn` telemetry when investigating skipped ticks or slow turns.

The combat-economics summary and both fire-utility tools reject malformed or
partially written JSONL with a file-and-line diagnostic and exit status `2`;
they do not continue with a silently incomplete calibration sample.

Accuracy filtering is an optional diagnostic for historical noisy Java surfer
runs. Do not use it as the default result view:

```sh
tools/combat_economics_summary.py battle-results/runs/<legacy-run> \
  --accuracy-filter-threshold 0.30
```

Do not apply that filter to `bots/ports/basic-gf-surfer-port`; ported-surfer
runs are already the preferred clean benchmark.

For legacy BasicGFSurfer parity runs, also inspect for visible fixed-Java bot
immobility. If the Java bridge bot is stuck and the Python port farms a very
lopsided score, treat that run as suspect reference evidence instead of clean
parity proof.

Use runner tick sampling for a repeatable immobility sanity check:

```sh
scripts/run-battle.sh \
  --rounds 12 \
  --tick-sample 10 \
  --run-dir battle-results/runs/surfer-parity-sampled \
  bots/ports/basic-gf-surfer-port \
  --legacy basic-gf-surfer

tools/bot_motion_sanity.py \
  battle-results/runs/surfer-parity-sampled/runner.log \
  --bot BasicGFSurferFixed \
  --json-output battle-results/runs/surfer-parity-sampled/motion-sanity.json

tools/intent_gap_summary.py battle-results/runs/surfer-parity-sampled
```

`bot_motion_sanity.py` reports suspect rounds and, when `runner.log` contains
round results, a clean/suspect score split. Treat the clean score as the useful
parity signal and the suspect score as bridge-glitch context.

The input can also be a run directory or a series directory; the tool will find
nested `runner.log` files and aggregate the clean/suspect score split:

```sh
tools/bot_motion_sanity.py \
  battle-results/series/<series-dir> \
  --bot BasicGFSurferFixed \
  --json-output battle-results/series/<series-dir>/motion-sanity.json
```

## A/B Runs

Main wrapper:

```sh
scripts/run-ab.sh --name EXPERIMENT --preset adaptive-1v1-core
```

Presets:

| Preset | Scope |
| --- | --- |
| `adaptive-1v1-core` | Adaptive vs Chase, Circle, Sweep. |
| `chase-1v1-core` | Chase vs Adaptive, Circle, Sweep. |
| `circle-1v1-core` | Circle vs Adaptive, Chase, Sweep. |
| `sweep-1v1-core` | Sweep vs Adaptive, Chase, Circle. |
| `adaptive-melee-core` | Four local bots. |
| `adaptive-1v1-basic-gf-surfer-port` | Preferred Python BasicGFSurfer port. |
| `adaptive-1v1-basic-gf-surfer` | Historical/noisy converted BasicGFSurfer reference only. |

Typical comparison:

```sh
scripts/run-ab.sh \
  --name adaptive-gun-change \
  --preset adaptive-1v1-basic-gf-surfer-port \
  --baseline <baseline-worktree> \
  --candidate <candidate-worktree> \
  --rounds 24 \
  --repeats 3 \
  --telemetry

tools/combat_economics_summary.py battle-results/ab/<experiment>
```

Use `1-8` rounds for smoke checks, `12-16` rounds for exploration, and
`24 x 3` for promotion. Ask before spending `50+` rounds. Converted legacy
opponents are not quality gates; port useful opponents into `bots/ports/`
before treating them as tuning targets.

Use `run-ab.sh` for real baseline/candidate comparisons. When validating one
current tree against a reference bot, use `scripts/run-battle-series.sh`
instead; invoking A/B without distinct worktrees compares the same dirty tree on
both sides and is not a meaningful promotion gate.

## Battle Series

```sh
scripts/run-battle-series.sh --runs 5 --rounds 24 bots/adaptive-prime bots/chase-lock
```

Use this when you need quick variance checks without a baseline/candidate A/B
layout.

## Converted Legacy Bots

Converted legacy support remains for parity checks, historical comparisons, and
porting work. Keep broad legacy aliases out of benchmark docs until they have
native Python ports:

```sh
scripts/run-battle.sh --list-legacy
scripts/run-battle.sh --rounds 10 bots/adaptive-prime --legacy basic-gf-surfer
```

The preferred strategy is to port useful opponents under `bots/ports/` and tune
against those ports. The current primary surfer target is:

```sh
scripts/run-battle.sh --rounds 24 bots/adaptive-prime bots/ports/basic-gf-surfer-port
```

## Common Workflows

```sh
# Quick smoke
scripts/run-battle.sh --rounds 1 bots/adaptive-prime bots/chase-lock

# Debug a behavior
scripts/run-battle.sh --rounds 3 --debug --telemetry --telemetry-open bots/adaptive-prime bots/chase-lock
tools/telemetry_audit.py battle-results/runs/<run>/telemetry --require-bot adaptive-prime

# Validate a code change
PYTHONPATH=bots .venv/bin/python -m pytest
git diff --check
scripts/run-ab.sh --name candidate-check --preset adaptive-1v1-core --baseline <baseline-worktree> --candidate <candidate-worktree>
```
