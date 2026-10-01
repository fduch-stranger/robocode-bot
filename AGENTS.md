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
- For porting a reference opponent into `bots/ports/`, read
  [docs/legacy-bot-porting-guideline.md](docs/legacy-bot-porting-guideline.md).

## Repository Layout

- `bots/adaptive-prime/`: 1v1 champion candidate.
- `bots/chase-lock/`: target-lock pressure bot.
- `bots/circle-strafer/`: defensive orbital bot.
- `bots/sweep-pressure/`: direct sweep-pressure bot.
- `bots/ports/`: native Python ports of reference opponents.
  `basic-gf-surfer-port` is the fixed 1v1 benchmark for Adaptive Prime.
  `tomcat-port` (lxx.Tomcat 3.68) and `diamond-port` (voidious.Diamond 1.8.28)
  are stronger experimental opponents, not baselines. Tuning work never edits
  any port.
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
scripts/run-battle.sh --rounds 1 bots/adaptive-prime bots/ports/diamond-port
scripts/run-ab.sh --name smoke --preset adaptive-1v1-core --rounds 1 --repeats 1
tools/ab_pool.py --candidate battle-results/ab/<experiment> --baseline battle-results/ab/<experiment>
tools/telemetry_audit.py battle-results/runs/<run>/telemetry --require-bot adaptive-prime
```

Legacy-bot checks, when `legacy-bots/` or `ROBOCODE_LEGACY_BOTS_ROOT` is
configured. Converted Java bots barely work through the bridge, so they are
porting references only, never a validation gate; Diamond and Tomcat have
native ports instead:

```sh
scripts/run-battle.sh --list-legacy
scripts/run-battle.sh --rounds 1 bots/adaptive-prime --legacy drussgt
scripts/run-battle.sh --rounds 1 bots/adaptive-prime --legacy saguaro
```

Use the telemetry viewer only when behavior inspection is needed. Keep telemetry
off for A/B benchmarking unless the task is specifically about telemetry.

## Benchmarking

- A tuning change is promoted only by the A/B standard in
  [docs/tooling.md#ab-runs](docs/tooling.md#ab-runs): 24 rounds x 6 repeats
  against the BasicGFSurfer port, judged with `tools/ab_pool.py` against the
  pooled baseline of the same code. Neutral results are rejected and recorded
  in [docs/plans/adaptive-prime-roadmap.md](docs/plans/adaptive-prime-roadmap.md).
- A 24 x 6 A/B takes about 30 minutes. Launch it detached so a tool timeout
  cannot kill it, and run nothing CPU-heavy alongside it: one concurrent
  profiler caused 27 skipped turns in a single run and skews the result.

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
- Ports under `bots/ports/` stay fixed so A/B results remain comparable;
  change one only to fix its fidelity to the original bot, and say so, because
  every pooled baseline against it is invalid afterwards.
- Ports are altered versions of other authors' work. Keep each original
  notice: Diamond's zlib license lives in `bots/ports/diamond-port/LICENSE`,
  Tomcat's source is "All Rights Reserved" by Alexey Zhidkov, and every port
  README credits its author. Mark any new port as altered and record the
  original notice the same way.

### Semantic Tooling

**Important:** Use semantic tooling when it can improve accuracy or reduce broad
text scans.

- Prefer Serena for symbol lookup, references, renames, and symbol-level
  edits. `.serena/project.yml` pins the LSP backend with the Python language
  server, so Serena's own symbol tools work without an IDE; JetBrains/IDE MCP
  tools remain fine for moves, safe deletes, and inspections when available.
- Use concrete file paths for file-oriented symbol operations. Use directory
  scopes only for tools that explicitly support them, such as symbol search.
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
  After a schema change, regenerate the contract with
  `tools/telemetry_schema_docs.py --output docs/telemetry-schema.md`.
- Port changes: run the port's unit tests and a battle against another port.
- Documentation changes: run `git diff --check` and check local Markdown links
  when links were edited.
