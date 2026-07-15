# Documentation

Navigation hub for the Robocode bot workspace.

## Start By Task

| Task | Page |
| --- | --- |
| Set up, package, run battles, use telemetry, run A/B checks | [Tooling](tooling.md) |
| Understand shared bot behavior | [Shared Bot Systems](bot-shared-systems.md) |
| Understand shared structures and formulas | [Bot Core Data Structures](bot-core-data-structures.md) |
| Inspect generated telemetry events | [Telemetry Event Schema](telemetry-schema.md) |
| Port converted legacy bots to native Python | [Legacy Bot Porting Guideline](legacy-bot-porting-guideline.md) |
| Review concrete gun packages | [Gun Component Docs](#gun-component-docs) |
| Tune or inspect a specific bot | [Bot Docs](#bot-docs) |
| Review local championship snapshot | [Championship Results](championship-results.md) |
| Review research plans | [Plans](plans/README.md) |

## Bot Docs

| Bot | Focus |
| --- | --- |
| [Adaptive Prime](../bots/adaptive-prime/README.md) | champion candidate, surfing, potential fields, adaptive firepower |
| [Chase Lock](../bots/chase-lock/README.md) | target-lock pressure and range-band movement |
| [Circle Strafer](../bots/circle-strafer/README.md) | stable orbit, wall escape, separation |
| [Sweep Pressure](../bots/sweep-pressure/README.md) | sweeping pressure and projected wall avoidance |
| [BasicGFSurfer Port](../bots/ports/basic-gf-surfer-port/README.md) | native Python surfer reference opponent |

## Gun Component Docs

Concrete virtual guns live under `bots/bot_core/gun/guns`.

| Gun package | Focus |
| --- | --- |
| [Gun Components](../bots/bot_core/gun/guns/README.md) | component contract and runtime flow |
| [Head-On](../bots/bot_core/gun/guns/head_on/README.md) | direct current-position baseline |
| [Linear](../bots/bot_core/gun/guns/linear/README.md) | constant-velocity intercept prediction |
| [Displacement](../bots/bot_core/gun/guns/displacement/README.md) | target-history displacement matching |
| [Dynamic Cluster](../bots/bot_core/gun/guns/dynamic_cluster/README.md) | KNN guess-factor learning |
| [Traditional GF](../bots/bot_core/gun/guns/traditional_gf/README.md) | global and fixed flight/lateral/wall-margin GF profiles |
| [Anti-Surfer](../bots/bot_core/gun/guns/anti_surfer/README.md) | low-density profile aiming |

## Add New Docs

- New user workflow or script: [Tooling](tooling.md).
- New shared behavior: [Shared Bot Systems](bot-shared-systems.md).
- New shared structure, approximation, or formula:
  [Bot Core Data Structures](bot-core-data-structures.md).
- New gun behavior: the relevant gun package README.
- Bot-specific strategy or tuning: that bot README.
- Longer research or validation plan: `docs/plans/`.
