# Robocode Bot Workspace

Python bots, shared combat logic, battle automation, telemetry tooling, and
algorithm notes for Robocode Tank Royale.

The bots target [Robocode Tank Royale](https://github.com/robocode-dev/tank-royale),
the modern Robocode engine and game server. Official project documentation is
available at [robocode.dev](https://robocode.dev/).

## Highlights

- Four local bots with different personalities: adaptive 1v1, chase pressure,
  defensive orbiting, and sweep pressure.
- Shared `bot_core` systems for target memory, radar locking, virtual guns,
  enemy-fire detection, movement learning, fire gates, and structured telemetry.
- CLI battle runner, legacy-bot support, A/B experiments, telemetry audit, and
  a browser telemetry dashboard for inspecting bot state and decision streams.
- Tracked architecture docs and local championship summaries so tuning choices
  are easier to review.

![Telemetry viewer showing an all-bot run](docs/assets/telemetry-viewer.png)

## Project Map

| Area | Purpose |
| --- | --- |
| `bots/` | bot packages plus shared `bot_core` code |
| `scripts/` | user-facing commands for setup, packaging, battles, telemetry, and A/B runs |
| `tools/` | Java battle runner, telemetry viewer, A/B runner, and audit utilities |
| `docs/` | documentation hub for workflows, shared systems, and data structures |
| `tests/` | unit tests for shared bot logic and tooling |

## Requirements

- Python 3.13 or compatible Python 3.x supported by the project virtualenv.
- Java runtime for the embedded Robocode Tank Royale runner.
- Bash-compatible shell for the scripts.
- Optional: converted legacy bots under `legacy-bots/` or
  `ROBOCODE_LEGACY_BOTS_ROOT`.

## First Run

```sh
cp .env.example .env
scripts/setup.sh
scripts/package.sh
scripts/run-battle.sh
```

This creates local configuration, installs dependencies, packages the bots, and
runs a default battle with every local bot.

## Tracked Snapshot

`Adaptive Prime` is the tracked local champion candidate. The recorded
round-robin and boss-bot benchmark summary is in
[Championship Results](docs/championship-results.md).

Quick health checks:

```sh
PYTHONPATH=bots .venv/bin/python -m pytest
scripts/run-battle.sh --rounds 1 bots/adaptive-prime bots/chase-lock
scripts/run-battle.sh --telemetry --rounds 1 bots/adaptive-prime bots/chase-lock
```

## Documentation

| Need | Read |
| --- | --- |
| Set up the repo, package bots, run battles, use telemetry, run A/B experiments, use legacy bots | [Tooling](docs/tooling.md) |
| Understand common bot behavior: radar, virtual guns, movement learning, fire gates, telemetry semantics | [Shared Bot Systems](docs/bot-shared-systems.md) |
| Understand implementation structures: KNN buffers, waves, stats buffers, prediction data | [Bot Core Data Structures](docs/bot-core-data-structures.md) |
| Understand concrete gun component behavior and package ownership | [Gun Component Docs](docs/README.md#gun-component-docs) |
| Inspect the generated telemetry event contract | [Telemetry Event Schema](docs/telemetry-schema.md) |
| Inspect or tune a specific bot | [Bot Docs](docs/README.md#bot-docs) |
| Browse all documentation | [Documentation Index](docs/README.md) |

## Bots

| Bot | Role | Documentation |
| --- | --- | --- |
| Adaptive Prime | 1v1 champion candidate with go-to surfing, potential fields, and adaptive firepower | [README](bots/adaptive-prime/README.md) |
| Chase Lock | target-lock pressure bot with range-band chase movement | [README](bots/chase-lock/README.md) |
| Circle Strafer | stable defensive orbital bot | [README](bots/circle-strafer/README.md) |
| Sweep Pressure | direct pressure bot with sweeping movement | [README](bots/sweep-pressure/README.md) |

All bots share helper code from `bots/bot_core`.

## Common Workflows

| Workflow | Entry Point |
| --- | --- |
| Package bots for the Robocode GUI | [Tooling: Packaging](docs/tooling.md#packaging) |
| Run 1v1 or melee battles from the CLI | [Tooling: Battle Runner](docs/tooling.md#battle-runner) |
| Use the telemetry dashboard | [Tooling: Telemetry Viewer](docs/tooling.md#telemetry-viewer) |
| Validate telemetry JSONL files | [Tooling: Telemetry Audit](docs/tooling.md#telemetry-audit) |
| Compare baseline and candidate bots | [Tooling: A/B Testing](docs/tooling.md#ab-testing) |
| Run converted legacy bots as enemies | [Tooling: Legacy Bots](docs/tooling.md#legacy-bots) |

## License

Licensed under the Apache License, Version 2.0. See [LICENSE](LICENSE).

## Battle Outputs

CLI battles write run artifacts under:

```text
battle-results/runs/<timestamp>/
```

The most useful files are `results.json`, `runner.log`, `process.log`,
optional `debug/`, optional `telemetry/`, and optional recordings. See
[Tooling: Battle Runner](docs/tooling.md#battle-runner) for the full artifact
reference.

## Local Configuration

Copy `.env.example` to `.env` and adjust machine-specific paths there. `.env` is
ignored by git.

Common local settings:

- `PYTHON_BIN`
- `ROBOCODE_PYTHON_BIN`
- `ROBOCODE_LEGACY_BOTS_ROOT`
- `ROBOCODE_TELEMETRY_DIR`
- `ROBOCODE_TELEMETRY_HOST`
- `ROBOCODE_TELEMETRY_PORT`
- `ROBOCODE_TELEMETRY_QUEUE_SIZE`
- `ROBOCODE_TELEMETRY_SYNC`
- `ROBOCODE_DEBUG_QUEUE_SIZE`
- `ROBOCODE_DEBUG_SYNC`
