# Robocode Bot Workspace Overview

This repository develops Python bots for Robocode Tank Royale, targeting the upstream engine at https://github.com/robocode-dev/tank-royale and docs at https://robocode.dev/.

Main layout:
- `bots/adaptive-prime/`: 1v1 champion candidate with go-to surfing, potential fields, adaptive firepower.
- `bots/chase-lock/`: target-lock pressure bot with range-band chase movement.
- `bots/circle-strafer/`: defensive orbital bot.
- `bots/sweep-pressure/`: direct sweep-pressure bot.
- `bots/bot_core/`: shared bot logic used by all bots.
- `scripts/`: setup, packaging, battle, telemetry, A/B wrappers.
- `tools/`: Java battle runner, telemetry viewer, A/B runner, telemetry audit.
- `docs/`: documentation hub and canonical architecture/tooling docs.
- `tests/`: unit tests for shared logic and tooling.

Start with `README.md`, then `docs/README.md` to pick task-specific documentation. Use bot-specific READMEs for individual bot strategy and tuning notes.