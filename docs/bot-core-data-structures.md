# Bot Core Data Structures

This is the compact implementation map for shared structures in `bots/bot_core`.
Behavior-level notes live in [Shared Bot Systems](bot-shared-systems.md), and
the generated telemetry contract lives in [Telemetry Event Schema](telemetry-schema.md).

## System Map

```mermaid
flowchart TD
    A["Bot callbacks"] --> B["TargetSnapshot / TargetMemory"]
    B --> C["VirtualGunSystem"]
    B --> D["MovementFlattener"]
    B --> E["EnemyFireDetector"]
    C --> F["GunWaveTracker"]
    C --> G["GunRegistry"]
    C --> H["AimModeSelector"]
    D --> I["MovementWaveStore"]
    D --> J["MovementDangerModel"]
    E --> I
    F --> K["Telemetry"]
    I --> K
```

## Target Data

| Structure | Module | Purpose |
| --- | --- | --- |
| `TargetSnapshot` | `bot_core.target_snapshot` | Canonical scan cache: id, energy, location, direction, speed, seen turn. |
| `TargetMemory` | `bot_core.targeting` | Stale/fresh target queries and active fire-threat lookup. |
| `TargetSelector` | `bot_core.targeting` | Reacquire-age filtering plus bot-specific score callback. |
| `TargetHistoryStore` | `bot_core.gun.context` | Bounded per-target movement history for context tags and history-backed guns. |
| `TargetPosition` | `bot_core.gun.models` | Historical target state plus observed lateral/advancing speed, wall margin, and distance. |
| `OwnMotionTracker` | `bot_core.motion` | Recent acceleration, direction-change age, and decel age for movement-wave features. |

Important invariant:

```text
target_age = current_turn - seen_turn
```

## Gun Data

| Structure | Purpose |
| --- | --- |
| `GunRuntimeConfig` | Bot wiring boundary for system, selector, scoring, and component factories. |
| `FireContext` | Fire-time tactical context: movement tags, flight time, lateral direction/confidence, wall margin, escape balance, distance/firepower buckets. |
| `AimContext` | Shared input passed to concrete guns. |
| `GunBearing` | Concrete gun candidate bearing plus optional GF/context/metadata. |
| `AimSolution` | Selected aim result returned to bots. |
| `GunWave` | Fired or eval bullet wave used to score virtual guns. |
| `WaveVisit` / `GunVisit` | Resolved wave result for telemetry, scoring, and component learning. |
| `GunStats` | Per-target/per-mode visits, hits, and rolling score. |
| `GunModeTraits` | Generic selector labels for role/family/phase/context strengths. |
| `GunSwitchCandidate` | Selector diagnostic record with raw/adjusted score, penalties, bonuses, visits, thresholds, and reason. |
| `GunRegistry` | Holds concrete gun components. |
| `VirtualGunSystem` | Bot-facing facade for context, bearings, waves, scoring, selection, and telemetry data. |
| `GunWaveTracker` | Pending/fired wave retention and cleanup. |
| `VirtualGunScorer` | Virtual-bearing score updates. |
| `AimModeSelector` | Sticky mode selection gates. |
| `RollingKnnBuffer` | Dynamic Cluster sample memory. |
| `GuessFactorProfile` | Traditional GF package-local histogram. |

Concrete gun packages:

| Package | State |
| --- | --- |
| [`head_on`](../bots/bot_core/gun/guns/head_on/README.md) | Stateless direct bearing. |
| [`linear`](../bots/bot_core/gun/guns/linear/README.md) | Stateless intercept and wall-aware diagnostics. |
| [`displacement`](../bots/bot_core/gun/guns/displacement/README.md) | Reads `TargetHistoryStore`, ranks similar replay candidates, chooses density-supported replay cluster. |
| [`dynamic_cluster`](../bots/bot_core/gun/guns/dynamic_cluster/README.md) | Owns KNN memory, neighbor weighting, bandwidth/peak diagnostics, and sample insertion. |
| [`traditional_gf`](../bots/bot_core/gun/guns/traditional_gf/README.md) | Owns global and fixed flight/lateral/wall-margin GF profiles, source-aware selector context, and diagnostics. |

## Gun Wave Flow

```text
aim target
create pending GunWave
fire bullet
promote pending wave to fired wave
update waves until target intercept
score all virtual bearings
update production stats and component learners
emit WaveVisit telemetry
```

Eval waves follow the same scoring path but stay out of production stats and
component learners unless selector policy explicitly uses eval evidence as a
read-only bonus.

Guess-factor basics:

```text
bearing_offset = actual_bearing - fire_bearing
guess_factor = bearing_offset / wall_limited_escape_angle
bullet_speed = 20 - 3 * firepower
gun_heat = 1 + firepower / 5
```

Bearings and escape angles are in degrees; `wall_limited_escape_angle` is
clamped to `[0.1, asin(8 / bullet_speed)]`.

Dynamic Cluster density bandwidth, with constants from
`DynamicClusterGunConfig`:

```text
hit_angle = degrees(atan2(18, distance))
gf_hit_width = hit_angle / max(0.1, positive_escape_angle, negative_escape_angle)
bandwidth = clamp(gf_hit_width * bandwidth_hit_width_scale, bandwidth_min, bandwidth_max)
density(candidate_gf) = sum(weight * exp(-((sample_gf - candidate_gf) / bandwidth)^2))
```

Geometry helpers live in `bot_core.geometry`; bullet physics lives in
`bot_core.physics`.

## Movement Data

| Structure | Purpose |
| --- | --- |
| `MovementWave` | Enemy bullet wave used for surf/danger learning. |
| `MovementWaveStore` | Active movement waves and cleanup. |
| `MovementProfile` | Per-enemy movement GF bins. |
| `MovementStatsBufferSet` | Segmented movement danger ensemble. |
| `MovementDangerModel` | Combines profile, ensemble, unvisited-bin, wall, and travel danger. |
| `MovementFlattener` | Shared facade used by bots. |
| `SurfingPlanner` | Go-to surf candidate generation and scoring. |
| `MovementCommand` | Testable movement output abstraction. |
| `ShadowBullet` | Bullet-shadow approximation based on actual fired bullet state. |

Movement-wave features include distance, lateral speed, acceleration, wall
margin, bullet power, and recent direction-change/decel age. The predictor uses
Tank Royale target-speed order: speed update, move along previous direction,
turn limit, wall clip, and zero speed after wall hit.

## Energy And Enemy Fire

| Structure | Purpose |
| --- | --- |
| `EnergyDropConfig` | Shared thresholds for fire/noise classification. |
| `EnemyEnergyCorrectionLedger` | Tracks correction for known non-fire energy changes: our bullet damage (positive) the enemy's `3 * power` gain when its bullet hits us (negative), ram damage (`0.6`), and an upper bound of enemy wall-hit damage (`enemy_wall_hit_damage_bound`: speed dropped to zero while pinned at the wall margin). Scanned energy is recorded before bullet hits resolve, so bullet corrections observed on turn `T` apply to the first scan after `T`; wall and ram damage is applied before the scan and uses a same-turn delay of `0`. |
| `EnemyFireDetector` | Shared sequence for corrected drop classification, gun heat, fire-power samples, and telemetry. |
| `EnemyFirePowerPredictor` | KNN-style enemy bullet-power prediction. |
| `GunHeatTracker` | Expected enemy fire readiness. |
| `FireDecision` | Shared fire-gate result and hold reason. |

Accepted enemy fire normally satisfies:

```text
0.1 <= corrected_drop <= 3.0
scan_gap <= policy limit
not collision/noise
```

## Advisor Data

Experimental; used only by `bots/adaptive-jev`.

| Structure | Meaning |
| --- | --- |
| `StyleFeatures` | Battle-level enemy movement: mean speed and lateral speed relative to us, lateral reversals per 100 scans, reversal lift near our wave passes, pooled within-round distance spread and trend, mean turn rate, collisions per round, wall-time share, and the linear gun's hit rate. |
| `SurfFeatures` | One confirmed enemy wave: distance, power, flight turns, our speed and lateral share, wall-limited escape room in each direction as a share of the open-field escape angle, and recent enemy hit guess factors. |
| `SurfRecord` | An asked wave waiting for both its answer and its visit. |

Reversal lift:

```text
lift      = (reversals within 2 turns of one of our wave passes / reversals)
          / (scans within 2 turns of one of our wave passes / scans)
pass turn = our fire turn + round(distance at fire / bullet speed)
```

The surf outcome option uses the guess factor relative to our lateral direction
at fire time: `forward` when `gf >= 0.3`, `reverse` when `gf <= -0.3`, and
`stop` otherwise. The Phase 2 information test compares the hit rate when Jev's
choice matched the outcome option with the hit rate when it did not (a
one-sided two-proportion z-test).

## Telemetry Records

JSONL envelope:

```text
{
  "bot": "...",
  "event": "...",
  "turn": 123,
  "state": {...},
  "fields": {...}
}
```

Common field meanings should stay stable across bots: `target`, `distance`,
`power`, `damage`, `bullet_id`, `aim_mode`, `gun_mode`, `movement_mode`,
`mode`, `evasion`, `evading`, `wall_risk`, and `reason`.

Use:

- `tools/telemetry_audit.py` for schema and attribution checks.
- `tools/combat_economics_summary.py` for score, firepower, damage, and
  per-gun real conversion.
- `tools/gun_eval_summary.py` for virtual-gun calibration and selector
  diagnostics.

## Extension Rules

- Put shared behavior and data structures in `bots/bot_core`.
- Keep bot personality in bot-local config/README files.
- Add exact formulas here only when multiple systems use them.
- Put workflow commands in [Tooling](tooling.md), not in every bot README.
- Add concrete gun details to the relevant gun package README.
