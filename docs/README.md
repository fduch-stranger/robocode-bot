# Documentation

This is the navigation hub for the Robocode bot workspace.

## Start By Task

| Task | Page |
| --- | --- |
| Set up the repo, package bots, run battles, use telemetry, run A/B experiments | [Tooling](tooling.md) |
| Understand common bot behavior: radar, virtual guns, movement learning, fire gates, telemetry | [Shared Bot Systems](bot-shared-systems.md) |
| Understand implementation structures: KNN buffers, waves, stats buffers, prediction data | [Bot Core Data Structures](bot-core-data-structures.md) |
| Understand concrete gun behavior and package boundaries | [Gun Component Docs](#gun-component-docs) |
| Inspect the generated telemetry event contract | [Telemetry Event Schema](telemetry-schema.md) |
| Review tracked local championship results | [Championship Results](championship-results.md) |
| Review research and tuning plans | [Plans](plans/README.md) |
| Tune or inspect a specific bot | [Bot Docs](#bot-docs) |

## Bot Docs

| Bot | Focus |
| --- | --- |
| [Adaptive Prime](../bots/adaptive-prime/README.md) | 1v1 champion candidate, go-to surfing, potential fields, adaptive firepower |
| [BasicGFSurfer Port](../bots/ports/basic-gf-surfer-port/README.md) | native Python port of the fixed BasicGFSurfer legacy benchmark |
| [Chase Lock](../bots/chase-lock/README.md) | target-lock pressure, range-band chase movement, conservative firepower |
| [Circle Strafer](../bots/circle-strafer/README.md) | stable orbiting, wall escape, separation, defensive movement |
| [Sweep Pressure](../bots/sweep-pressure/README.md) | sweeping pressure, projected wall avoidance, direct engagement |

## Gun Component Docs

Concrete virtual guns live under `bots/bot_core/gun/guns`. Start with the
package overview when changing orchestration or selector boundaries, then read
the specific gun package before changing a component's behavior or telemetry.

| Gun package | Focus |
| --- | --- |
| [Gun Components](../bots/bot_core/gun/guns/README.md) | component contract, runtime flow, package ownership |
| [Head-On](../bots/bot_core/gun/guns/head_on/README.md) | direct current-position baseline |
| [Linear](../bots/bot_core/gun/guns/linear/README.md) | constant-velocity intercept prediction |
| [Displacement](../bots/bot_core/gun/guns/displacement/README.md) | target-history displacement matching |
| [Dynamic Cluster](../bots/bot_core/gun/guns/dynamic_cluster/README.md) | KNN guess-factor learning and sample memory |
| [Traditional GF](../bots/bot_core/gun/guns/traditional_gf/README.md) | global, exact-segment, and coarse-segment GF profiles |
| [Anti-Surfer](../bots/bot_core/gun/guns/anti_surfer/README.md) | low-density profile aiming against surfing bias |

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

- [Telemetry Event Schema](telemetry-schema.md)
  - canonical dashboard fields
  - event categories
  - required and optional fields
  - analyzer aliases

- [Championship Results](championship-results.md)
  - 1v1 round-robin ranking
  - head-to-head results
  - melee confirmation
  - local-only artifacts

- [Plans](plans/README.md)
  - active bot tuning plans
  - research hypotheses
  - validation checklists

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
- New concrete gun or package-local gun behavior: add or update that gun's
  README under `bots/bot_core/gun/guns/` and link it from
  [Gun Component Docs](#gun-component-docs).
- Bot-specific strategy, mode, or tuning note: add to that bot README.
- Longer research or tuning plan: add to `docs/plans/` and link from the
  relevant bot README.
