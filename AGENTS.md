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
scripts/run-battle.sh --rounds 1 bots/adaptive-prime --legacy drussgt
scripts/run-battle.sh --rounds 1 bots/adaptive-prime --legacy saguaro
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
- Do not revert unrelated user changes in the working tree.

### Semantic Tooling

**Important:** Use semantic tooling when it can improve accuracy or reduce broad
text scans.

- Prefer Serena and JetBrains/IDE MCP tools for symbol lookup, references,
  renames, moves, safe deletes, and inspections.
- For JetBrains-backed Serena symbol tools, use concrete file paths for
  file-oriented operations. Use directory scopes only for tools that explicitly
  support them, such as symbol search.
- Before behavior, tooling, or architecture changes, list Serena memories and
  read the project memories that match the task.
- Update Serena project memories when durable architecture, tooling, workflow,
  or tuning context changes; keep them concise and remove or rewrite stale
  project records.

## Verification Expectations

Choose verification based on the change:

- Shared math or helper changes: run the relevant unit tests, preferably the full
  test suite.
- Bot behavior changes: run at least a short CLI battle; use A/B runs for
  performance-sensitive changes.
- Telemetry changes: run a telemetry battle and `tools/telemetry_audit.py`.
- Documentation changes: run `git diff --check` and check local Markdown links
  when links were edited.
