# Shared Bot Systems

This page describes shared behavior used by multiple bots. For concrete fields
and implementation structures, see [Bot Core Data Structures](bot-core-data-structures.md).

## Control Loop

Most bots follow the same turn shape:

```text
scan/update target memory
detect enemy fire
select target
update gun and movement waves
aim and select gun
choose radar command
choose movement command
fire if gate passes
emit telemetry
```

Adaptive uses the most shared infrastructure. Chase, Circle, and Sweep still
keep some local target/movement policy code, but they share the same core
contracts for target snapshots, guns, fire detection, movement learning, and
telemetry.

## Targets And Radar

Scans become `TargetSnapshot` records keyed by enemy id. The critical value is:

```text
target_age = current_turn - seen_turn
```

Target age drives stale-target cleanup, fire gating, radar reacquire, target
selection, and telemetry interpretation.

Radar helpers live in `bot_core.radar`:

- `lock`: target is fresh enough to track; lock can lead the target and uses
  distance-aware overscan.
- `reacquire`: known target is stale or needs a wider sweep.
- `search`: no usable target.

## Virtual Guns

The shared gun facade is `VirtualGunSystem`. It builds `AimContext` and
`FireContext`, asks registered gun components for bearings, selects a live mode,
tracks waves, scores visits, and emits telemetry.

Live repo-bot modes:

| Mode | Role |
| --- | --- |
| `dynamic_cluster` | Primary KNN guess-factor learner. |
| `displacement` | Situational history-replay gun. |
| `traditional_gf` | Situational profile guess-factor gun. |
| `linear` | Early/simple-motion fallback. |

Force-testable modes also include `head_on`, `linear_wall_aware`, and
`anti_surfer`.

Selection is sticky. A candidate must be available, meet visit and score floors,
and beat the current mode by the configured margin. `GunModeTraits` and generic
decision context keep selector logic role-aware without hard-coding concrete
gun classes. `gun.switch_decision` is the main telemetry event for explaining
selected, blocked, unavailable, or superseded candidates.

Temporary gun overrides:

```text
ROBOCODE_GUN_MODE
ROBOCODE_GUN_SET
ROBOCODE_ADAPTIVE_GUN_MODE / _GUN_SET
ROBOCODE_CHASE_GUN_MODE / _GUN_SET
ROBOCODE_CIRCLE_GUN_MODE / _GUN_SET
ROBOCODE_SWEEP_GUN_MODE / _GUN_SET
```

Use ignored `.env.guns` for GUI experiments.

## Fire Gate

Shared fire helpers live in `bot_core.energy`. Bots generally require:

```text
fresh target
gun aligned
safe own energy margin
valid firepower
```

`gun_bearing` telemetry is an alignment error, not an absolute heading. `0`
means the gun is aligned. Hold reasons are reported through `FireDecision`.
Adaptive has an explicit low-energy endgame override and emits
`gun.low_energy_endgame` diagnostics when it considers or uses that path.

## Enemy Fire

Enemy fire is inferred from corrected energy drops:

```text
0.1 <= corrected_drop <= 3.0
scan gap within policy
not close-collision noise
```

Accepted fire creates a movement wave, enemy fire-power sample, gun-heat update,
and evasion window. Expected fire can also be generated from gun heat, but
direct energy-drop evidence wins over stale heat estimates.

## Movement

Shared movement code lives in `bot_core.movement`.

Common pieces:

- movement waves from enemy fire
- guess-factor movement bins
- segmented danger buffers
- movement flattening
- go-to surfing
- bullet shadows from real bullet state
- minimum-risk movement for melee

`MovementFlattener` is the main facade. Internally it delegates wave storage,
profile danger, stats-buffer danger, and surfing candidate selection to smaller
helpers. Movement prediction follows Tank Royale target-speed order closely:
speed update, movement along previous direction, turn limit, wall clipping, and
zero speed after wall collision.

Minimum-risk movement scores candidate destinations using enemy proximity,
focus-target distance, wall/travel risk, recent-destination penalty, and
optional fire-threat terms. Destinations are sticky for a short time to avoid
jitter.

## Telemetry

Telemetry is JSONL. Common events:

| Event | Purpose |
| --- | --- |
| `bot.config` | Startup gun/eval configuration. |
| `bot.turn_timing` | Per-turn decision elapsed time, remaining turn budget, and pressure severity. |
| `bot.skipped_turn` | Engine skipped-turn event with the last recorded decision timing context. |
| `track` | High-level target/radar/aim/movement/fire state. |
| `gun.switch` | Initial or changed selected gun mode. |
| `gun.switch_decision` | Selector candidate diagnostics. |
| `gun.wave_visit` | Production virtual-gun wave scoring. |
| `gun.eval_wave_visit` | Optional neutral eval-wave scoring. |
| `gun.traditional_gf_profile` | Traditional GF source/model diagnostics. |
| `gun.fire_drift` | Planned wave vs actual fired bullet state. |
| `bullet.fired` / `bullet.hit_bot` | Our real fire and hits. |
| `enemy.fire_detected` / `enemy.gun_heat_wave` | Confirmed or expected enemy fire. |
| `hit.bullet` | Enemy bullet hit on us. |
| `movement.profile_visit` / `movement.flatten` | Movement learning and direction flips. |
| `movement.goto_surf` / `movement.minimum_risk` | Movement planner decisions. |

Shared schema and analyzer semantics live in `bot_core.telemetry.schema` and
[Telemetry Event Schema](telemetry-schema.md). Use [Tooling](tooling.md) for
viewer, audit, and experiment-analysis commands.
