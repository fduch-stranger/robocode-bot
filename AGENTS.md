# Agent Guide

This repository develops Python bots for Robocode Tank Royale. Future agents
should treat the root README and `docs/` as the source of truth before changing
bot behavior or tooling.

## Start Here

- Read [README.md](README.md) for the project map and common workflows.
- Read [docs/README.md](docs/README.md) to choose the right detailed doc.
- For scripts and local setup, read [docs/tooling.md](docs/tooling.md).
- For shared bot behavior, read
  [docs/bot-shared-systems.md](docs/bot-shared-systems.md).
- For KNN buffers, waves, movement stats, and telemetry record structure, read
  [docs/bot-core-data-structures.md](docs/bot-core-data-structures.md).
- For bot-specific strategy, read that bot's `README.md`.

## Repository Layout

- `bots/adaptive-prime/`: 1v1 champion candidate.
- `bots/chase-lock/`: target-lock pressure bot.
- `bots/circle-strafer/`: defensive orbital bot.
- `bots/sweep-pressure/`: direct sweep-pressure bot.
- `bots/bot_core/`: shared bot logic used by all bots.
- `scripts/`: user-facing setup, packaging, battle, telemetry, and A/B commands.
- `tools/`: battle runner, telemetry viewer, A/B runner, and audit utilities.
- `tests/`: unit tests for shared logic and tooling.

## Local Environment

- Copy `.env.example` to `.env` for machine-specific settings.
- Keep `.env`, `battle-results/`, `dist/`, `.venv/`, and `legacy-bots/`
  uncommitted.
- `ROBOCODE_LEGACY_BOTS_ROOT` may point to converted legacy bots. If it is empty,
  scripts use the repo-local ignored `legacy-bots/` directory.
- Do not add absolute local paths or usernames to public docs or defaults.

## Common Commands

```sh
scripts/setup.sh
scripts/package.sh
scripts/run-battle.sh
```

Useful checks:

```sh
PYTHONPATH=bots .venv/bin/python -m pytest
scripts/run-battle.sh --rounds 1 bots/adaptive-prime bots/chase-lock
scripts/run-ab.sh --name smoke --preset adaptive-1v1-core --rounds 1 --repeats 1
tools/telemetry_audit.py battle-results/runs/<run>/telemetry --require-bot adaptive-prime
```

Legacy-bot checks, when `legacy-bots/` or `ROBOCODE_LEGACY_BOTS_ROOT` is
configured:

```sh
scripts/run-battle.sh --list-legacy
scripts/run-battle.sh --rounds 1 bots/adaptive-prime --legacy basic-gf-surfer
scripts/run-battle.sh --rounds 1 bots/adaptive-prime --legacy hawk-on-fire
scripts/run-battle.sh --rounds 1 bots/adaptive-prime --legacy diamond
scripts/run-ab.sh --name boss-smoke --preset adaptive-1v1-boss --rounds 1 --repeats 1
```

Use the telemetry viewer only when behavior inspection is needed. Keep telemetry
off for A/B benchmarking unless the task is specifically about telemetry.

## Development Rules

- Prefer changes in `bots/bot_core/` when behavior is genuinely shared.
- Keep bot-specific personality and strategy in the individual bot directory.
- Update bot README files when a bot's state machine, movement mode, gun policy,
  or telemetry semantics change.
- Update `docs/tooling.md` when scripts or workflows change.
- Update `docs/bot-shared-systems.md` when common behavior changes.
- Update `docs/bot-core-data-structures.md` when shared data structures,
  approximations, or math change.
- Avoid duplicating formulas and command references across docs; link to the
  canonical doc instead.
- Use `apply_patch` for manual edits.
- Do not revert unrelated user changes in the working tree.

## Bot Behavior Notes

- `Adaptive Prime` is optimized for 1v1 first. When improving it, validate with
  1v1 A/B runs before spending time on melee behavior.
- `Chase Lock`, `Circle Strafer`, and `Sweep Pressure` should get shared-system
  improvements only when they fit their strategy.
- Fire decisions should be tied to fresh scans, gun bearing error, energy, range,
  and gun confidence.
- Movement work should be validated with battle results and telemetry, not only
  code inspection.

## Verification Expectations

Choose verification based on the change:

- Shared math or helper changes: run the relevant unit tests, preferably the full
  test suite.
- Bot behavior changes: run at least a short CLI battle; use A/B runs for
  performance-sensitive changes.
- Telemetry changes: run a telemetry battle and `tools/telemetry_audit.py`.
- Documentation changes: run `git diff --check` and check local Markdown links
  when links were edited.
