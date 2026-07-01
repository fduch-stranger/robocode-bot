# Robocode Bot Workspace

This repository is a workspace for developing Python bots for Robocode Tank
Royale. It contains the bots, shared bot logic, local battle tooling,
telemetry/debugging tools, A/B benchmarks, and documentation for the algorithms
used by the bots.

The bots target [Robocode Tank Royale](https://github.com/robocode-dev/tank-royale),
the modern Robocode engine and game server. Official project documentation is
available at [robocode.dev](https://robocode.dev/).

## Project Map

| Area | Purpose |
| --- | --- |
| `bots/` | bot packages plus shared `bot_core` code |
| `scripts/` | user-facing commands for setup, packaging, battles, telemetry, and A/B runs |
| `tools/` | Java battle runner, telemetry viewer, A/B runner, and audit utilities |
| `docs/` | documentation hub for workflows, shared systems, and data structures |
| `tests/` | unit tests for shared bot logic and tooling |

## First Run

```sh
cp .env.example .env
scripts/setup.sh
scripts/package.sh
scripts/run-battle.sh
```

This creates local configuration, installs dependencies, packages the bots, and
runs a default battle with every local bot.

## Documentation

| Need | Read |
| --- | --- |
| Set up the repo, package bots, run battles, use telemetry, run A/B experiments, use legacy bots | [Tooling](docs/tooling.md) |
| Understand common bot behavior: radar, virtual guns, movement learning, fire gates, telemetry semantics | [Shared Bot Systems](docs/bot-shared-systems.md) |
| Understand implementation structures: KNN buffers, waves, stats buffers, prediction data | [Bot Core Data Structures](docs/bot-core-data-structures.md) |
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
