# Documentation

This is the navigation hub for the Robocode bot workspace.

## Start By Task

| Task | Page |
| --- | --- |
| Set up the repo, package bots, run battles, use telemetry, run A/B experiments | [Tooling](tooling.md) |
| Understand common bot behavior: radar, virtual guns, movement learning, fire gates, telemetry | [Shared Bot Systems](bot-shared-systems.md) |
| Understand implementation structures: KNN buffers, waves, stats buffers, prediction data | [Bot Core Data Structures](bot-core-data-structures.md) |
| Review latest local championship results | [Championship Results](championship-results.md) |
| Tune or inspect a specific bot | [Bot Docs](#bot-docs) |

## Bot Docs

| Bot | Focus |
| --- | --- |
| [Adaptive Prime](../bots/adaptive-prime/README.md) | 1v1 champion candidate, go-to surfing, potential fields, adaptive firepower |
| [Chase Lock](../bots/chase-lock/README.md) | target-lock pressure, range-band chase movement, conservative firepower |
| [Circle Strafer](../bots/circle-strafer/README.md) | stable orbiting, wall escape, separation, defensive movement |
| [Sweep Pressure](../bots/sweep-pressure/README.md) | sweeping pressure, projected wall avoidance, direct engagement |

## Tooling Docs

- [Tooling](tooling.md)
  - setup and `.env`
  - packaging
  - battle runner
  - telemetry viewer
  - telemetry audit
  - A/B testing
  - battle series
  - legacy bots

- [Championship Results](championship-results.md)
  - 1v1 round-robin ranking
  - head-to-head results
  - melee confirmation
  - legacy boss check

## Architecture Docs

- [Shared Bot Systems](bot-shared-systems.md)
  - common control loop
  - target cache
  - radar modes
  - virtual guns
  - movement learning
  - fire gates
  - telemetry semantics

- [Bot Core Data Structures](bot-core-data-structures.md)
  - target snapshots
  - gun waves and movement waves
  - rolling KNN memory
  - guess-factor profiles
  - movement stats buffers
  - enemy fire-power prediction
  - telemetry record structure

## Where To Add New Docs

- New user workflow or script: add to [Tooling](tooling.md).
- New shared bot behavior: add to [Shared Bot Systems](bot-shared-systems.md).
- New shared data structure or approximation: add to [Bot Core Data Structures](bot-core-data-structures.md).
- Bot-specific strategy, mode, or tuning note: add to that bot README.
