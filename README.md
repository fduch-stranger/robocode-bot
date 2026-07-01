# Robocode Bot Workspace

This repository contains Python bots for Robocode Tank Royale, plus tooling for
packaging, running battles, logging decisions, and viewing live bot telemetry.

## Bots

- `bots/adaptive-prime`: strongest composite bot with adaptive movement and virtual-gun targeting
- `bots/chase-lock`: target-locking chase bot
- `bots/circle-strafer`: evasive circle-strafing bot
- `bots/sweep-pressure`: pressure bot with sweeping movement

All bots share helper code from `bots/bot_utils`.

## Quick Start

Create your local configuration file:

```sh
cp .env.example .env
```

Edit `.env` if your Python executable, telemetry port, or legacy bot directory
is different from the defaults. Use `PYTHON_BIN` for creating `.venv`; use
`ROBOCODE_PYTHON_BIN` only when you want bot launchers and telemetry tooling to
run with a specific Python instead of the repo `.venv`. The `.env` file is
private and ignored by git.

Install dependencies:

```sh
scripts/setup.sh
```

Package all bots:

```sh
scripts/package.sh
```

Run a default battle with every local bot:

```sh
scripts/run-battle.sh
```

The packaged bot archives are written to `dist/`.

## Using The Robocode GUI

Package first:

```sh
scripts/package.sh
```

Then add the bots from `dist/` in the Robocode Tank Royale GUI. Each zip
contains one bot plus the shared `bot_utils` package it needs.

Packaged bots do not require this repository's `.venv`. Their launchers use
`ROBOCODE_PYTHON_BIN` when it is set, otherwise they use `.venv/bin/python` if
one exists next to the package, and finally fall back to `python3`.

If you want live internals while using the GUI, start telemetry before launching
the battle:

```sh
scripts/telemetry-ui.sh start
```

This opens a browser dashboard and enables telemetry for GUI-launched bots.
When you are done:

```sh
scripts/telemetry-ui.sh disable
```

## Running Battles From The CLI

Run two bots as a 1v1 battle:

```sh
scripts/run-battle.sh bots/adaptive-prime bots/chase-lock
```

Run three or more bots as a melee battle:

```sh
scripts/run-battle.sh bots/adaptive-prime bots/chase-lock bots/circle-strafer
```

Use more rounds for less noisy results:

```sh
scripts/run-battle.sh --rounds 30 bots/adaptive-prime bots/chase-lock
```

Use a fixed output directory:

```sh
scripts/run-battle.sh --run-dir battle-results/runs/manual-1 bots/adaptive-prime bots/chase-lock
```

With no bot arguments, `scripts/run-battle.sh` discovers every bot directory
under `bots/` that contains a bot JSON manifest. Helper directories such as
`bots/bot_utils` are ignored.

## A/B Bot Experiments

Use A/B experiments before accepting movement, targeting, or bullet-power
changes. The default A/B runner keeps telemetry off, runs the same preset
against a baseline and a candidate worktree, then writes a manifest and summary.

Run the core Adaptive 1v1 benchmark:

```sh
scripts/run-ab.sh \
  --name go-to-surfing \
  --baseline /path/to/baseline/repo \
  --candidate /path/to/candidate/repo \
  --preset adaptive-1v1-core
```

For a quick local smoke test, compare the current worktree against itself:

```sh
scripts/run-ab.sh --name smoke --preset adaptive-1v1-core --rounds 1 --repeats 1
```

Available presets:

- `adaptive-1v1-core`: Adaptive Prime against Chase Lock, Circle Strafer, and Sweep Pressure
- `adaptive-melee-core`: all four local bots in one melee battle
- `adaptive-1v1-boss`: Adaptive Prime against configured legacy boss bots

Each experiment writes:

- `manifest.json`: command, preset, git SHA, dirty status, bot paths, rounds, repeats
- `summary.json`: machine-readable score, first-place, survival, and damage deltas
- `summary.md`: readable A/B table and final win/mixed/regression decision

Default decision thresholds are intentionally simple: a score drop worse than
2% or a first-place drop beyond the repeat count is marked as a regression.

## Battle Artifacts

Each run writes files under `battle-results/runs/<timestamp>/`, unless you pass
`--run-dir`.

- `results.json`: structured final scores
- `runner.log`: runner lifecycle, round, boot, and optional sampled tick events
- `process.log`: raw Robocode runner, server, and booter output
- `debug/`: bot decision logs when `--debug` is enabled
- `telemetry/`: live telemetry JSONL files when `--telemetry` is enabled
- `recordings/game-*.battle.gz`: battle recordings when `--record` is enabled
- `intents.jsonl`: captured bot intents when `--intent-diagnostics` is enabled

## Debug Logs

Enable text decision logs:

```sh
scripts/run-battle.sh --debug bots/adaptive-prime bots/chase-lock
```

Debug logs are useful when you want grep-friendly evidence about target
selection, radar mode, gun mode, movement mode, fire decisions, and hit events.

## Live Telemetry Dashboard

Enable the browser dashboard during a CLI battle:

```sh
scripts/run-battle.sh --telemetry bots/adaptive-prime bots/chase-lock
```

Open the viewer automatically:

```sh
scripts/run-battle.sh --telemetry --telemetry-open bots/adaptive-prime bots/chase-lock
```

The dashboard shows:

- bot position, energy, heading, gun direction, and radar direction
- selected target and target distance
- movement mode and evasion state
- active gun mode, firepower, and confidence
- derived gun accuracy, damage trade, energy efficiency, and average range
- enemy fire response, collision risk, target reacquisition, and mode churn
- gun-mode and movement-mode timelines for spotting stale decisions or tunneling
- recent hits, fires, gun switches, movement decisions, and wave visits

Telemetry is optional. When it is disabled, bots keep their normal behavior.

Stop a background viewer for a run directory:

```sh
scripts/telemetry-ui.sh stop --dir battle-results/runs/<run>/telemetry
```

List running or stale telemetry viewers:

```sh
scripts/telemetry-ui.sh list
```

Stop every discovered telemetry viewer:

```sh
scripts/telemetry-ui.sh stop-all
```

`stop-all` only stops viewer processes. If GUI telemetry is enabled, a bot
launched from the Robocode GUI can start a viewer again. Disable GUI telemetry
when you want GUI-launched bots to stop publishing telemetry:

```sh
scripts/telemetry-ui.sh disable
```

Check GUI telemetry status:

```sh
scripts/telemetry-ui.sh status
```

## Legacy Bot Enemies

Converted legacy bots can be used as external enemies. By default, tooling looks
in `../selected-legacy-bots-copy`. Override that with `--legacy-root` or
`ROBOCODE_LEGACY_BOTS_ROOT` in `.env`.

For headless battles, `scripts/run-battle.sh` creates a small shim under the
run directory for each legacy bot. The shim keeps the original converted bot
directory untouched and adds `-Djava.awt.headless=true`, which avoids macOS AWT
startup crashes from converted legacy wrappers.

Run against BasicGFSurfer:

```sh
scripts/run-battle.sh --rounds 10 bots/adaptive-prime --legacy basic-gf-surfer
```

Use a legacy bot as an explicit bot argument:

```sh
scripts/run-battle.sh bots/adaptive-prime legacy:wiki.BasicGFSurfer_1.02
```

List available converted legacy bots:

```sh
scripts/run-battle.sh --list-legacy
```

Add every converted legacy bot from the legacy root:

```sh
scripts/run-battle.sh --legacy all
```

## Advanced Runner Options

Write structured results to a specific file:

```sh
scripts/run-battle.sh --rounds 30 --results battle-results/adaptive-vs-chase.json bots/adaptive-prime bots/chase-lock
```

Enable battle recording, intent diagnostics, and sampled tick logs:

```sh
scripts/run-battle.sh --record --intent-diagnostics --tick-sample 25
```

Use `--help` to see every option:

```sh
scripts/run-battle.sh --help
```
