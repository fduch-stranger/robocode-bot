# Robocode Bot Workspace Overview

This repository develops Python bots for Robocode Tank Royale, targeting the upstream engine at https://github.com/robocode-dev/tank-royale and docs at https://robocode.dev/.

Main layout:
- `bots/adaptive-prime/`: 1v1 champion candidate with option surfing, potential fields, adaptive firepower.
- `bots/ports/`: native Python ports of reference opponents; `basic-gf-surfer-port` is the fixed 1v1 benchmark for Adaptive Prime, and `tomcat-port` and `diamond-port` are stronger experimental opponents. No port is edited by tuning work.
- `bots/chase-lock/`: target-lock pressure bot with range-band chase movement.
- `bots/circle-strafer/`: defensive orbital bot.
- `bots/sweep-pressure/`: direct sweep-pressure bot.
- `bots/bot_core/`: shared bot logic used by all bots.
- `scripts/`: setup, packaging, battle, telemetry, A/B wrappers.
- `tools/`: Java battle runner, telemetry viewer, A/B runner and pooling, telemetry audit, recording-to-GIF renderer.
- `docs/`: documentation hub and canonical architecture/tooling docs.
- `tests/`: unit tests for shared logic and tooling.

Start with `README.md`, then `docs/README.md` to pick task-specific documentation. Use bot-specific READMEs for individual bot strategy and tuning notes.