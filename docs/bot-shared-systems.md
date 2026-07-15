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
and beat the current mode by the configured margin. Role-specific margins can
make primary warm-up easier while requiring stronger evidence before a fallback
replaces an active primary. `GunModeTraits` and generic decision context keep
selector logic role-aware without hard-coding concrete gun classes.
`gun.switch_decision` is the main telemetry event for explaining selected,
blocked, unavailable, or superseded candidates.

When shot policy changes firepower after selection, `VirtualGunSystem` can
re-aim the already selected mode without invoking or mutating the selector a
second time. The re-aim preserves committed switch metadata while updating the
bearing, features, fire context, and diagnostics for the actual power.

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
Bots can use a shared `last_stand` fire-gate path when energy is critically low:
the target must be fresh, distance-limited, tightly aligned, and the shot must
leave a small energy reserve. This path bypasses the normal reserve and
critical-energy holds only for those controlled shots.

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

## Combat Ledger

`CombatProfileStore` is a shared, telemetry-first ledger for accepted-shot and
damage economics. Adaptive Prime is the first consumer. It records:

- engine-accepted own bullets and their actual power;
- hit, wall, bullet-collision, and round-end resolutions;
- inferred enemy shots with scan-gap confidence;
- real enemy hits and whether a movement wave was matched.

Lifetime totals are paired with a common recent turn window. The ledger does
not use separate event-count deques, so sparse fire and hit streams are not
silently compared across different time spans. `combat.profile` is sampled
during tracking and emitted at round close; `bullet.resolved` exposes the final
outcome of each accepted own bullet. A late winning-hit callback can replace a
provisional round-end miss through `bullet.resolution_corrected`. Because the
runner can stop a defeated process before terminal callbacks finish, offline
summaries reconcile durable accepted-shot and real-hit events at EOF and count
remaining in-flight bullets as misses. Terminal target cleanup preserves a
pending gun wave until the lower-priority accepted-fire callback, while a truly
targetless accepted bullet is retained in an unattributed ledger bucket. These
observations are telemetry-only and do not currently change fire, gun
selection, or movement.

## Shadow Fire Utility

`FireUtilityCalibrator` estimates the value of the power already selected by
Adaptive Prime. It learns only from engine-accepted bullets after their real
outcome is known. Pending requests, virtual waves, and the shot being predicted
do not enter its support, so each prediction is causal.

Every ready-gun turn emits `fire.utility_opportunity` with the current
behavior's `fire` or `hold` action and unchanged `FireDecision` reason. An
accepted engine bullet emits `fire.utility_accepted`; its eventual hit, wall,
bullet collision, or round-end miss emits `fire.utility_outcome`. A late hit
can correct a provisional terminal miss through
`fire.utility_outcome_corrected`. Calibration uses the causal global posterior
as its base rate. Dynamic Cluster solutions at or above the held-out `0.10`
quality threshold receive one conservative fixed odds adjustment; range,
accepted-power, other gun modes, and generic maturity remain diagnostic only. A
ready fire snapshot remains pending across later hold opportunities until the
engine reports whether it accepted that command. Exact formulas and thresholds
are in [Core Data Structures](bot-core-data-structures.md).

This path is shadow-only: no utility value is read by the fire gate, power
policy, gun selector, or movement. Adaptive's first Phase 5A fire/hold candidate
was rejected at its telemetry smoke because the global base probability became
a battle-wide hold switch. Its live gate and experiment flag were removed.
`tools/fire_utility_summary.py` reconciles durable real hits and reports
reliability by probability, range, power, mode, quality, fallback level, and
chronological window.

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

Adaptive Prime currently maintains an explicit legacy composite profile for
the unchanged live movement score and three separate diagnostic channels:
confirmed-wave occupancy, matched real enemy hits, and transient
confidence-weighted expected-wave pressure. `movement.evidence_shadow` and the
extended `movement.goto_surf` fields compare the live choice with a clean
evidence formula. Real hits never enter the occupancy channel, and expected
waves leave no permanent clean-profile evidence.

Adaptive's bounded split-evidence candidate uses occupancy weight `0.65`, hit
weight `1.5` with a `2.0` component cap, and expected-pressure weight `0.35`
with a `1.5` component cap. Hit-only selection starts at support `6`. Its
focused `3 x 24` A/B increased enemy bullet damage in every repeat, so the live
selection branch and experiment flag were removed. The legacy score remains
live; the bounded formula remains diagnostic-only shadow telemetry.

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
| `combat.profile` | Recent and lifetime accepted-shot, damage, enemy-fire-confidence, and attribution totals. |
| `bullet.resolved` | Final accepted own-bullet outcome and gun attribution. |
| `bullet.resolution_corrected` | Late winning-hit correction to a provisional terminal miss. |
| `fire.utility_opportunity` | Shadow utility and current fire/hold reason whenever the gun is ready. |
| `fire.utility_accepted` | Causal utility prediction bound to an engine-accepted bullet. |
| `fire.utility_outcome` / `fire.utility_outcome_corrected` | Real outcome and any late correction for the accepted prediction. |
| `movement.evidence_shadow` | Live versus shadow direction with occupancy, hit, expected-pressure, support, and fallback components. |
| `movement.profile_visit` / `movement.flatten` | Movement learning and direction flips. |
| `movement.goto_surf` / `movement.minimum_risk` | Movement planner decisions. |

Shared schema and analyzer semantics live in `bot_core.telemetry.schema` and
[Telemetry Event Schema](telemetry-schema.md). Use [Tooling](tooling.md) for
viewer, audit, and experiment-analysis commands.

Sampled events are throttled independently by event name and restart their
sampling window when the engine resets the turn number for a new round. One
high-frequency event therefore cannot suppress another event such as `track`.
