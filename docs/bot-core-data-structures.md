# Bot Core Data Structures

This document describes shared structures used by the bots in `bots/bot_core`.
It is the place for implementation-level concepts that are reused across bots:
target snapshots, virtual guns, waves, KNN buffers, rolling statistics,
movement danger buffers, enemy fire prediction, and telemetry records.
The generated event contract lives in
[Telemetry Event Schema](telemetry-schema.md).

The implementation is intentionally experimental. These structures are tuned for
fast iteration and readable telemetry rather than maximum theoretical accuracy.

## System Map

```mermaid
flowchart TD
    A["Bot event callbacks"] --> B["TargetSnapshot cache"]
    B --> T["TargetMemory / TargetSelector"]
    T --> C["VirtualGunSystem"]
    T --> D["MovementFlattener"]
    B --> E["EnemyFirePowerPredictor"]
    E --> F["GunHeatTracker"]
    C --> G["GunWaveTracker"]
    C --> H["RollingKnnBuffer"]
    C --> I["GunStats and GF profiles"]
    D --> J["MovementWaveStore"]
    D --> K["MovementProfile bins"]
    D --> L["MovementStatsBufferSet"]
    D --> M["ShadowBullet list"]
    F --> J
    G --> N["Telemetry events"]
    J --> N
    K --> N
    L --> N
```

## Core Snapshots

### `TargetSnapshot`

Location: `bot_core.target_snapshot`

```text
TargetSnapshot(
  bot_id,
  energy,
  x,
  y,
  direction,
  speed,
  seen_turn
)
```

This is the canonical per-enemy scan cache. Bots keep a dictionary keyed by
`bot_id`. Almost every targeting, radar, movement, and fire-power decision reads
from this structure.

Important derived value:

```text
target_age = current_turn - seen_turn
```

Bots use target age to decide if a target is still safe to fire at, whether
radar should reacquire, and when stale targets should be dropped.

### `TargetMemory` and `TargetSelector`

Location: `bot_core.targeting`

`TargetMemory` wraps a per-enemy snapshot mapping and provides common queries:

```text
stale_ids(current_turn, max_age)
fresh_targets(current_turn, max_age)
active_fire_threat(threat_id, threat_turn, current_turn, memory_turns)
```

`TargetSelector` applies reacquire-age filtering and delegates scoring to bot
strategy code. Adaptive Prime uses these wrappers directly. The other local bots
still hold ordinary dictionaries of `TargetSnapshot` values and local selection
helpers, so target lifecycle behavior is only partially centralized today.

### Own Motion Snapshots

Location: `bot_core.motion`

`OwnMotionTracker` records recent acceleration, direction-change age, and decel
age for the bot itself. These values become movement-wave features, so movement
danger learning can distinguish "I was accelerating near a wall" from "I was
moving laterally in open field."

## Virtual Gun Data

Location: `bot_core.gun`

### Main Structures

| Structure | Purpose |
| --- | --- |
| `GunRuntimeConfig` | Composed runtime wiring used by bots. It contains system, selector, scoring, and component-factory inputs. |
| `FireContext` | Shared fire-time tactical context: movement tags, bullet flight time, lateral direction/confidence, wall margin, wall-limited escape shape, and coarse distance/firepower buckets. |
| `GunSample` | One learned target escape sample for KNN: target id, turn, feature vector, guess factor, and fire context. |
| `GunWave` | A simulated bullet wave for a fired shot or optional neutral evaluation opportunity. Used to score virtual guns when it reaches the target. Fire context is stored directly, and component metadata is carried generically in `gun_metadata`. |
| `GunStats` | Per-target/per-mode visits, hits, and rolling score. |
| `GuessFactorProfile` | Component-local decayed histogram for profile guns. Traditional GF and anti-surfer keep separate profile types under their component packages. |
| `AimSolution` | Output of aiming: predicted point, bearing error, selected mode, features, fire context, mode-change info, and component diagnostics keyed by mode. |
| `GunModeTraits` | Generic gun labels used by the selector: role, family, phase, and context strengths. |
| `GunSwitchCandidate` | Per-candidate selector diagnostic with adjusted/raw score, confidence/source penalties, trait/context bonus, visits, thresholds, margin, generic decision source, and rejection/selection reason. |
| `WaveVisit` | Telemetry/learning result when a gun wave reaches the target, with fire context and component diagnostics keyed by mode. |
| `RollingKnnBuffer` | Dynamic-cluster component memory for per-target bounded `GunSample` records. |
| `AimContext` | Shared aiming input passed from the facade to concrete gun components. Includes bot/target state, firepower, normalized features, fire context, segment key, field margin, disabled mode set, and movement-history tags. |
| `GunBearing` | Concrete gun output: mode, absolute bearing, optional guess factor, optional decision context, and generic metadata. |
| `GunVisit` | Resolved production/eval wave data passed to gun components. Production visits update learners; eval visits remain isolated. |
| `GunRegistry` | Holds concrete gun components and gathers available bearings for the facade. |
| `VirtualGunSystem` | Stable bot-facing facade that orchestrates context building, component bearings, wave lifecycle, scoring, selection, and telemetry data assembly. |
| `GunWaveTracker` | Owns pending/fired gun wave retention and round/target cleanup. |
| `VirtualGunScorer` | Scores virtual bearings and updates global/segmented gun stats. |
| `AimModeSelector` | Applies mode switch visit, score, margin, confidence, and per-mode policy penalties. |

### Gun Components

Concrete guns live under `bot_core.gun.guns` and own their private aiming or
learning state. The package docs include behavior diagrams and ownership notes:

| Component | State |
| --- | --- |
| [`HeadOnGun`](../bots/bot_core/gun/guns/head_on/README.md) | Stateless direct bearing. |
| [`LinearGun`](../bots/bot_core/gun/guns/linear/README.md) | Stateless linear prediction variants using `bot_core.gun.prediction.LinearPrediction` diagnostics. |
| [`DisplacementGun`](../bots/bot_core/gun/guns/displacement/README.md) | Reads shared `TargetHistoryStore` to average matching historical displacement samples. |
| [`DynamicClusterGun`](../bots/bot_core/gun/guns/dynamic_cluster/README.md) | Owns `RollingKnnBuffer`, sample sequencing, neighbor selection, decayed weighting, bandwidth scoring, and warmup blending. |
| [`TraditionalGfGun`](../bots/bot_core/gun/guns/traditional_gf/README.md) | Owns global, exact-segment, and coarse-segment GF profiles, peak selection, source centering, source-aware selector context, and diagnostics. |
| [`AntiSurferGun`](../bots/bot_core/gun/guns/anti_surfer/README.md) | Owns anti-surfer profile bins and valley selection. |

Start from the [gun component package overview](../bots/bot_core/gun/guns/README.md)
when changing the shared component contract or runtime wiring.

### Gun Wave Lifecycle

```mermaid
sequenceDiagram
    participant Bot
    participant Gun as VirtualGunSystem
    participant Wave as GunWave
    participant Stats as GunStats/KNN

    Bot->>Gun: aim(target, distance, firepower)
    Gun-->>Bot: AimSolution(mode, bearing, features)
    Bot->>Gun: make_wave(...)
    Bot->>Gun: set_pending_wave(wave)
    Bot->>Bot: set_fire(power)
    Bot->>Gun: record_pending_fire()
    Gun->>Wave: store fired wave
    Bot->>Gun: update_waves(target)
    Gun->>Stats: score all virtual bearings
    Gun->>Stats: add KNN sample and GF visits
    Gun-->>Bot: WaveVisit telemetry
```

### Guess Factor Math

A gun wave records the bearing at fire time and the target lateral direction.
When the wave reaches the target:

```text
bearing_offset = actual_bearing - fire_bearing
guess_factor = bearing_offset / max_escape_angle
```

The code uses wall-limited positive and negative escape angles, not only the
theoretical maximum, so the denominator depends on which side of the firing
bearing the target escaped toward.

Bullet physics lives in `bot_core.physics`, while angle, position, and
guess-factor geometry lives in `bot_core.geometry`.

Wall-limited escape angles and go-to surfing use the shared movement predictor.
The predictor follows the Tank Royale turn order for target-speed movement:
update speed, move along the previous direction, apply the turn limit for that
new speed, then apply wall collision clipping and return a zero-speed state when
the move hit a wall. Its `distance_remaining` stop helper is a local planning
approximation; the Tank Royale server processes target speed, not a bot-side
distance command.

Bullet physics:

```text
bullet_speed = 20 - 3 * firepower
max_escape_angle = asin(8 / bullet_speed)
gun_heat = 1 + firepower / 5
```

### Virtual Gun Scoring

Every fired wave stores all virtual bearings available at fire time. When the
wave reaches the target, each virtual gun receives a score based on angular
error:

```text
hit_angle = atan2(18, target_distance)
score = max(0, 1 - abs(virtual_bearing - actual_bearing) / hit_angle)
```

`GunStats.rolling_score` is updated with an exponential rolling average:

```text
rolling_score = (1 - alpha) * rolling_score + alpha * score
```

Optional neutral evaluation waves use the same scoring math, but their stats
are stored separately from the production switcher stats. They do not add KNN
samples, update traditional/anti-surfer profiles, or affect `AimModeSelector`.
They are intended for telemetry comparisons against forced-gun battles.

`gun.fire_drift` compares each fired production wave against the actual
`BulletFiredEvent` bullet state. Use it to audit planned source point, selected
bearing, firepower, and bullet speed against the engine event before trusting
virtual-gun score gaps.

The final raw gun score blends rolling score and hit rate:

```text
raw_score = 0.7 * rolling_score + 0.3 * (hits / visits)
```

Segmented stats can blend global score with segment score when enough segment
visits exist:

```text
score = global_score * (1 - blend) + segment_score * blend
```

Traditional-GF profiles can choose peaks with either the strongest single bin
or an optional density-supported neighborhood. The default single-bin selector
preserves historical behavior. Density selection scores nearby mass around each
candidate bin and returns the neighborhood centroid, which lets experiments
prefer stable broad peaks over isolated spikes without changing histogram
smoothing or decay.

### Gun Switch Diagnostics

`AimModeSelector` evaluates only selectable guns that can currently produce a
bearing. Missing selectable guns are reported as `unavailable`. Available
candidates can be rejected for:

- `visits`: not enough mode-specific virtual-wave visits.
- `score_floor`: score below that mode's minimum switch score.
- `margin`: score does not beat the current gun by the configured margin.
- `superseded`: the candidate beats the current gun by the configured margin,
  but another candidate passed the same gates with a better score.

The selected candidate is reported as `selected`; the active gun is reported as
`current` when no switch occurs. These diagnostics are surfaced through
`gun.switch_decision` telemetry and do not change scoring by themselves.

When `GunSelectorConfig.switch_confidence_visits` and
`GunSelectorConfig.switch_confidence_penalty` are enabled, selector decisions
can apply a low-visit confidence penalty. Components can also provide
mode-specific decision penalties, context-aware gates, and trait/context
bonuses. Examples include source-aware `traditional_gf` penalties and
lower/higher visit or score floors based on profile source, KNN maturity
bonuses for primary learning guns, and low-lateral bonuses for linear fallback
guns. Selector decisions use an adjusted score:

```text
adjusted_score = raw_score - confidence_penalty - source_penalty + decision_bonus + eval_score_bonus
```

The adjusted score is clamped to `[0, 1]`. Candidate telemetry reports `score`
as the adjusted decision score and `raw_score` as the virtual-gun score before
decision penalties and bonuses. `eval_score_bonus`, `eval_visits`, and
`effective_visits` are selector-only evidence derived from the separate eval
scorer; they do not mutate production stats or concrete gun learners.

Role-aware switch margins are separate from scoring. The current repo configs
use a small primary-over-fallback margin so mature KNN can leave linear early,
a larger situational-over-primary margin so profile guns do not churn against
KNN, and a smaller slump margin only when the current primary gun has enough
low-score visits and the situational candidate has source/context evidence. If
a situational current gun's source degrades to global-only context, the selector
can mark that candidate with `reason=source_degraded` and lower its retention
advantage while still requiring alternatives to pass their normal gates.

`tools/gun_eval_summary.py` reports Traditional GF source diagnostics in three
layers: real fired/hit conversion by source, profile-weight and selected-GF
averages by source, and production/eval GF error by source. Use this to check
whether a profile source is actually converting before changing source trust
penalties or promoting a coarse-key experiment.

### KNN Gun Memory

`DynamicClusterGun` owns `RollingKnnBuffer`, which stores `GunSample` values
per target. Samples include the original normalized feature tuple and the
fire-time `FireContext`; context-aware weighting can bias neighbor evidence
toward similar movement tags, bullet flight time, wall-escape balance, and
lateral-direction confidence without replacing the feature tuple.

Memory limits:

```text
max_samples = 1200
max_samples_per_target = 900
```

The buffer trims oldest samples per target first, then trims globally by oldest
turn if the total count is too high.

KNN query flow:

```mermaid
flowchart LR
    A["current target features"] --> B["samples for target"]
    B --> C["feature distance"]
    C --> D["nearest neighbors"]
    D --> E["kernel density over GF candidates"]
    E --> F["best density bin"]
    F --> G["local peak centroid"]
```

Feature distance is weighted normalized Euclidean distance over the feature
tuple:

```text
weights = (2.0, 1.2, 1.8, 1.3, 0.8, 0.7, 0.9)
distance = sqrt(sum(weight_i * (left_i - right_i)^2))
```

Dynamic-cluster scores density candidates with context- and recency-weighted
neighbors:

```text
score(candidate) = sum(weight * exp(-((candidate - sample_guess_factor) / effective_bandwidth)^2))
```

The old best-bin center is retained in diagnostics. The selected guess factor
is a local weighted centroid of neighbor samples around the best density bin,
using an effective bandwidth adjusted by target hit width. Diagnostics report
peak margin, neighbor agreement, confidence, and ambiguous secondary peaks.

Samples can support decay through half-life weighting, but the current
configuration leaves gun KNN decay disabled by default:

```text
decayed_weight = 1.0            when half_life <= 0
decayed_weight = 0.5^(age/half_life) otherwise
```

## Movement Data

Location: `bot_core.movement`

### Main Structures

| Structure | Purpose |
| --- | --- |
| `MovementWave` | Enemy bullet wave, confirmed or expected. |
| `MovementWaveFeatures` | Lateral velocity, advancing velocity, flight time, acceleration, direction-change age, decel age, wall distance. |
| `MovementProfileVisit` | Recorded visit to a guess-factor bin for movement learning. |
| `MovementStatsBuffer` | Segmented danger histogram for a specific feature set. |
| `MovementStatsBufferSet` | Ensemble of multiple segmented buffers. |
| `MovementWaveStore` | Owns movement wave retention, matching, and target cleanup. |
| `MovementProfile` | Owns basic movement profile bins and decay. |
| `MovementDangerModel` | Builds per-bin danger breakdowns from profile and ensemble stats. |
| `SurfingPlanner` | Selects the nearest surfable wave for go-to surfing. |
| `FlatteningDecision` | Direction-switch decision for orbit/strafe movement. |
| `GoToSurfDecision` | Scored destination for go-to surfing. |
| `MovementCommand` | Movement command output: mode, turn, speed, telemetry fields, and optional direction update. |
| `ShadowBullet` | Our bullet used to lower danger where it intersects an enemy wave. |
| `MinimumRiskDecision` | Destination selected for melee minimum-risk movement. |

### Movement Wave

`MovementWave` represents an enemy bullet:

```text
target_id
source_x, source_y
direct_bearing
lateral_direction
bullet_speed
max_escape_angle_positive
max_escape_angle_negative
fired_turn
distance_bucket
kind = confirmed | expected
expected_confidence
features
```

Confirmed waves come from energy drops. Expected waves come from enemy gun heat
prediction.

### Movement Profile Bins

The basic movement profile is keyed by:

```text
(target_id, distance_bucket, guess_factor_bin)
```

Distance buckets:

```text
near: distance < 280
mid:  distance < 480
far:  otherwise
```

Bin count is 31. Nearby bins are smoothed:

```text
smoothed_count = bin[0] * 1.0
               + bin[-1] * 0.55 + bin[1] * 0.55
               + bin[-2] * 0.25 + bin[2] * 0.25
```

The profile decays when a target accumulates too many visits:

```text
if total_target_visits > profile_decay_after:
  every target profile bin *= 0.5
```

### Stats Buffer Ensemble

`MovementStatsBufferSet` contains several segmented buffers:

```text
distance
lateral
advancing
accel
wall
flight
distance_lateral
distance_wall
distance_flight
lateral_accel
lateral_wall
distance_decel
```

Each buffer maps:

```text
(target_id, segment_tuple, bin_index) -> decayed visit count
```

Each segment also stores an effective sample count:

```text
(target_id, segment_tuple) -> samples
```

On every write, the touched segment decays:

```text
visit *= stats_buffer_decay
drop visit if visit < 0.001
```

The ensemble danger is a confidence-weighted average across buffers:

```text
confidence = clamp(samples / stats_buffer_min_samples, 0, 1)
ensemble_danger = sum(buffer_danger * confidence) / sum(confidence)
```

The final learned danger is conservative. The ensemble can raise danger above
the base profile, but does not reduce it below the profile:

```text
ensemble_weight = stats_buffer_weight * clamp(ensemble_samples / stats_buffer_max_effective_samples, 0, 1)
learned_danger = profile_danger + max(0, ensemble_danger - profile_danger) * ensemble_weight
total_danger = learned_danger + unvisited_bin_danger
```

### Flattener Direction Selection

The flattener compares danger for current lateral direction and the opposite
direction. If the alternative is safer by the switch margin and cooldown allows
it, the bot flips direction.

```text
if alternative_count + switch_margin < current_count:
  switch direction
else:
  keep direction
```

With surfing enabled, it projects a future position until the wave intercepts.
Without surfing, it projects a simpler fixed lookahead point.

### Go-To Surfing

Go-to surfing generates candidate destinations around the current position and
simulates driving to each destination until the selected wave intersects.
The simulation uses the Tank Royale movement order: calculate new speed, move
along the old body direction, apply line-preserving wall clipping inside the
bot-radius field rectangle, then apply the body turn limited by the new speed.

Candidate score:

```text
danger = learned_danger + wall_risk + distance_risk + travel_risk
```

Where:

```text
wall_risk = goto_wall_weight / distance_from_wall
distance_risk = penalty for too close, too far, or away from preferred range
travel_risk = travel_distance * goto_travel_weight
```

The lowest danger candidate becomes a `GoToSurfDecision`.

### Bullet Shadow Approximation

`ShadowBullet` records our bullet path from the actual `BulletFiredEvent`
bullet state: source position, direction, speed, and fire turn. If our bullet
intersects a confirmed enemy wave near a guess-factor bin, that bin danger is
reduced:

```text
danger *= bullet_shadow_danger_multiplier
```

Expected waves do not use bullet shadows, because there is no confirmed enemy
bullet path to shadow.

### Minimum Risk Movement

Minimum-risk movement is used mainly in melee.

It creates candidate points around the bot and scores them by:

```text
risk = enemy_proximity
     + close_enemy_penalty
     + focus_target_distance_penalty
     + wall_risk
     + travel_risk
     + recent_destination_penalty
     + optional fire_threat terms
```

The active destination is sticky for a few ticks unless a new destination is
meaningfully lower risk.

### Movement Commands

`MovementCommand` separates movement choice from bot API application:

```text
MovementCommand(mode, turn, speed, telemetry_fields, direction_update)
```

Strategies can return strafe or destination-drive commands. The bot applies the
command in one place, which keeps direction mutation and `set_turn_left` /
`target_speed` calls out of scoring logic.

## Fire Gate Data

Location: `bot_core.energy`

`bot_core.energy` is a package. It keeps compatibility exports at the package
root while grouping energy drops, correction ledgers, fire detection, fire
gates, fire-power prediction, and gun heat into separate components.

`FireGate` evaluates common firing constraints and returns:

```text
FireDecision(can_fire, reason, alignment_limit)
```

Each bot supplies its own `FireGateConfig`, so strategy-specific thresholds stay
local while the decision ordering and hold reasons are shared. Current hold
reasons are:

```text
stale
critical_energy
low_energy_range
gun_alignment
energy_margin
ready
```

`EnemyFireDetector` returns `EnemyFireDetection(signal, distance,
previous_prediction, heat_state)` after consuming energy corrections, updating
gun heat for every scan, and recording fire-power prediction samples for
confirmed fire. Gun heat is context for expected-fire waves and telemetry; it is
not a hard veto over a valid energy-drop fire because scan timing and corrections
can make the heat estimate stale. Adaptive Prime, Circle Strafer, and Sweep
Pressure use this full detector. Chase Lock currently keeps local detection flow
while using the shared correction ledger and energy-drop classifier.

## Enemy Fire Prediction

Location: `bot_core.energy`

### Energy Drop Signal

Energy drops are classified as fire with:

```text
raw_drop = previous_energy - current_energy
corrected_drop = previous_energy - (current_energy + energy_correction)
```

`EnemyEnergyCorrectionLedger` stores short-lived per-target corrections for our
own bullet damage. Corrections are consumed for turns in this window:

```text
after_turn < correction_turn <= current_turn
```

The drop is accepted when:

```text
corrected_drop > 0
scan_gap <= max_scan_gap
min_fire_power <= corrected_drop <= max_fire_power
not close_collision_noise
```

If accepted:

```text
fire_power = corrected_drop
bullet_travel_ticks = round(distance / bullet_speed)
evade_ticks = clamp(bullet_travel_ticks + lead, min_evade_ticks, max_evade_ticks)
```

### Enemy Fire-Power KNN

`EnemyFirePowerPredictor` stores per-target samples:

```text
enemy_energy
our_energy
distance
fire_power
```

Features are normalized:

```text
enemy_energy / 100
our_energy / 100
distance / 650
```

Prediction uses nearest neighbors:

```text
weight = 1 / (0.08 + feature_distance)
predicted_power = sum(sample_power * weight) / sum(weight)
```

Before enough samples exist, prediction is blended with a heuristic:

```text
prediction = heuristic * (1 - blend) + knn * blend
confidence <= low_confidence_cap
```

The predictor also tracks mean absolute error when a previous prediction can be
compared to an observed fire power.

### Gun Heat Tracker

`GunHeatTracker` stores one `GunHeatState` per enemy:

```text
heat
last_turn
last_expected_wave_turn
observed_fire
```

Heat cools by:

```text
heat = max(0, heat - cooling_rate * elapsed_turns)
```

Observed fire sets:

```text
heat = 1 + fire_power / 5
```

When heat is ready and enough ticks passed since the last expected wave, the
tracker can create an expected enemy fire wave using predicted firepower.

## Telemetry Records

Location: `bot_core.telemetry`, `bot_core.debug`, and `tools/telemetry_viewer`

Telemetry is JSONL. Each record has:

```text
schema
ts
pid
bot
turn
event
state
fields
```

`state` is sampled from the live bot object:

```text
x, y, energy
direction, gun_direction, radar_direction
speed, target_speed
turn_rate, gun_turn_rate, radar_turn_rate
gun_heat, gun_cooling_rate
enemy_count
arena_width, arena_height
```

`fields` are event-specific and should carry decision context: target id,
distance, movement mode, aim mode, radar mode, firepower, gun bearing error,
danger breakdown, wave bin, prediction confidence, and so on.

`bot_core.telemetry.recorder.TelemetryRecorder` builds the JSONL envelope and
writes records through `bot_core.async_writer.AsyncItemWriter` by default. Bot
scripts call domain emitters such as `FireTelemetry`, `MovementTelemetry`,
`EnergyTelemetry`, and `TargetingTelemetry`; those emitters build event fields
from structured decision records or explicit status arguments. JSON
serialization, file writes, and flushes happen on the writer thread. If the
queue fills, telemetry events are dropped instead of blocking movement, radar,
or gun decisions; close writes a `telemetry.dropped` lifecycle event with the
dropped count.

`bot_core.debug.DebugLogger` owns debug-log sampling and forwards structured
events to the recorder. Text debug logs use the same bounded background-write
pattern and summarize dropped lines with `debug.dropped`. Domain-specific
telemetry modules build event fields from decision records such as `FireTick`,
`FireDecision`, `MovementCommand`, `TargetSelection`, and movement/gun wave
visits.

Important invariant: event fields should make derived dashboard stats possible
without re-running bot logic.

`bot_core.telemetry.schema` defines the shared telemetry contract used by tests
and audit tooling:

- canonical dashboard fields such as `target`, `distance`, `power`, `damage`,
  `bullet_id`, `aim_mode`, `movement_mode`, `evasion`, and `reason`
- known event names and categories such as fire, movement, targeting, energy,
  combat, and lifecycle
- required fields for analyzer-critical events
- compatibility aliases, for example `bot_id` to normalized `target` where the
  raw event describes an enemy bot id

The schema is intentionally small. It validates shared analyzer semantics while
still allowing bot-specific raw fields that are useful for strategy debugging.
When adding a telemetry event used by the dashboard or audit, add the event spec
and focused emitter tests with complete field-set assertions.

## Approximation Tradeoffs

The current implementation uses practical approximations:

- KNN is linear scan over bounded arrays, not a kd-tree.
- Kernel density is evaluated over candidate guess factors, not a continuous
  solver.
- Movement stats buffers use coarse buckets to keep memory bounded.
- Rolling scores use exponential averages instead of storing all historical
  outcomes.
- Linear prediction variants stay deliberately simple: `linear` assumes constant
  velocity, and `linear_wall_aware` reuses the shared movement predictor for
  wall clipping.
- Expected gun-heat waves are useful for early evasion, but less certain than
  energy-drop waves.
- Bullet shadowing is conservative and only reduces danger for confirmed waves.

These choices keep the code easy to inspect and telemetry-friendly while still
allowing stronger techniques to be added later.

## When To Extend

Add to this document when introducing:

- a new shared data structure in `bot_core`
- a new KNN feature vector or distance metric
- a new stats buffer, segment, or decay rule
- a new telemetry event schema used by the dashboard
- a new movement/gun approximation that affects bot behavior
