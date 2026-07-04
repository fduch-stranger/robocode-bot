# Core Combat Economics Plan

This plan turns the recent BasicGFSurfer findings into a coherent direction for
Adaptive Prime and the shared bot core. Adaptive is the evidence case because
it is the 1v1 champion candidate, but the implementation should be shared
wherever the behavior is generally better.

The goal is not to add more clever formulas. The goal is to make every repo bot
choose better fights: when to shoot, how hard to shoot, which gun to trust, and
how to move when the enemy is learning us.

## Problem

Adaptive can win rounds while losing the damage exchange. In the 2026-07-04
Adaptive-vs-`basic-gf-surfer-port` telemetry run, Adaptive won score and first
places but lost bullet damage badly:

| Bot | Score | Firsts | Bullet Damage |
| --- | ---: | ---: | ---: |
| Adaptive Prime | 895 | 9 | 304 |
| BasicGFSurfer Port | 774 | 3 | 548 |

Adaptive fired many low-power Dynamic Cluster shots. The port fired fixed
`1.9` bullets. Adaptive hit more often, but the port's hits were worth much
more. That means the core weakness is combat economics, not only aim.

The port also shows that a simple gun can work if its assumptions are aligned:
distance, velocity, last velocity, one shared lateral direction, and battle
persistent wave learning. Adaptive's movement is still repeatable enough in
simple guess-factor bins for that to matter.

Follow-up 2026-07-04 telemetry confirmation used two 24-round battles:

| Opponent | Raw Result | Bullet Damage Shape | Filtered Surfer View |
| --- | --- | --- | --- |
| `basic-gf-surfer-port` | Adaptive lost `1544-2007` despite `15-9` firsts | Adaptive `561` vs port `1328` | no high-accuracy rounds excluded; result unchanged |
| legacy `basic-gf-surfer` | Adaptive won `2115-1770` and `17-7` firsts | Adaptive `950` vs legacy `1234` | `4` rounds excluded; kept score `1424/20`, kept accuracy `15.4%` |

The legacy run explains why legacy BasicGFSurfer should not be a normal gate.
Raw Displacement looked very strong (`41/88`, `46.6%`), but after excluding
high-accuracy rounds it dropped to `8/52` (`15.4%`). Treat legacy results as
noisy historical context. The Python port cannot hit the same legacy glitch
mode and is the primary test target for this plan. The durable signal is still
combat economics: surfers hit less often but with roughly `1.9`-power bullets,
while Adaptive fires many low-power Dynamic Cluster shots.

## Goal

Build an opponent-responsive combat loop:

```text
observe enemy pressure
measure our shot value
choose whether to fire
choose firepower
choose gun by expected value
move to reduce enemy gun value
```

The result should be broadly useful against surfers, simple GF bots, KNN guns,
head-on punishers, and weak local bots. BasicGFSurfer is the current evidence
case, not a hard-coded target.

## Non-Goals

- Do not special-case bot names.
- Do not add a large opaque tactical model before simpler economics are tested.
- Do not hide bad guns with selector hacks when the real issue is firepower or
  movement predictability.
- Do not promote raw legacy BasicGFSurfer gains. The Python port is the primary
  clean surfer target for this plan.
- Do not make every metric a decision input. Telemetry-only diagnostics are
  allowed and should stay telemetry-only until useful.
- Do not preserve old behavior only because it is current behavior. If a shared
  replacement wins cleanly and explains itself in telemetry, the old path can
  be deleted instead of carried as compatibility debt.

## Compatibility Stance

This is a core-system plan. Prefer changes in `bots/bot_core/` over
bot-specific fixes when the behavior is generally useful. Adaptive Prime can be
the first rollout target because it has the strongest validation pressure, but
Chase Lock, Circle Strafer, and Sweep Pressure should inherit the same improved
combat economics after smoke validation.

Backward compatibility is not a goal by itself. Keep a compatibility layer only
when it protects a proven behavior, a necessary force-test hook, or a migration
path for experiments. If the old selector/fire/movement behavior is simply
worse and the new shared behavior is validated, remove the old code rather than
supporting both.

## Design Principles

1. Every new decision input must answer a battle question:
   - Are we being out-damaged?
   - Is the enemy hard to hit?
   - Is the enemy hitting us predictably?
   - Is this shot worth giving the enemy another wave?
   - Is this movement candidate landing in a danger region?

2. Prefer small rolling summaries over large models:
   - rolling hit rate
   - rolling damage per shot
   - rolling enemy hit rate
   - hit guess-factor danger by coarse state
   - recent damage deficit

3. Keep the loop inspectable:
   - each adjustment emits a reason
   - raw scores remain visible beside adjusted scores
   - every gate has an env kill switch during experiments

4. Implement in layers. A later layer must prove it adds value beyond earlier
   economics.

5. Put general improvements in shared systems:
   - opponent combat profile belongs in shared runtime state
   - shot value and firepower policy belong in shared fire decisions
   - enemy-gun danger belongs in shared movement scoring
   - bot-local config should express personality, not duplicate core logic

## Implementation Subplan: Wave Evidence Semantics

Before changing firepower or selector behavior, split the meaning of wave
evidence. The BasicGFSurfer port is not strong because its wave physics are
more advanced. It is strong because each wave observation has a clear purpose:
its gun learns from accepted-shot virtual visits, and its surfing danger is
anchored in real bullet hits.

Adaptive's current movement profile can mix ordinary enemy-wave pass visits
with real bullet-hit visits. That makes the danger surface partly describe
where Adaptive happened to be when waves arrived, not where the enemy gun
actually hit. This should be fixed first because later EV and movement decisions
should consume clean evidence, not compensate for polluted profiles.

### Evidence Kinds

Define explicit evidence kinds and keep their consumers separate:

| Evidence | Source | Primary consumer |
| --- | --- | --- |
| `gun_virtual_visit` | our accepted-shot gun wave reaches enemy position | gun learning and virtual-gun scoring |
| `movement_wave_pass` | confirmed enemy wave reaches our current position | flattening and anti-repetition pressure |
| `movement_bullet_hit` | real enemy bullet hit matched to a movement wave | enemy-gun danger |
| `expected_enemy_wave` | gun-heat or power prediction without confirmed drop | immediate movement planning with confidence penalty |

Do not write all four into the same long-term danger meaning. A wave pass says
"we occupied this GF region." A bullet hit says "the enemy gun punished this GF
region." Those are related, but they are not the same signal.

### Movement Profile Split

Replace the single movement-danger interpretation with separate stores:

```text
enemy_hit_profile
  updated only from matched real bullet hits
  high weight
  segmented by own-risk regime

visit_flattening_profile
  updated from ordinary confirmed wave passes
  low or medium weight
  used to avoid repeated occupancy, not to claim enemy aim danger

expected_wave_pressure
  optional telemetry-only or very low weight
  expires quickly unless confirmed
```

Candidate scoring should combine them explicitly:

```text
danger =
  enemy_hit_danger
  + small_flattening_penalty
  + immediate_expected_wave_pressure
  + wall/position risk
```

`movement_bullet_hit` should no longer be just "wave pass weight x3" in the
same table. It should update enemy-hit danger directly, while wave pass evidence
remains useful for flattening and anti-repetition.

### Own-Risk Regime

Bullet-hit danger should be keyed by the state the enemy gun saw when firing,
not only by final GF bin. Start with coarse buckets:

- distance bucket
- enemy bullet-power bucket
- our lateral bucket
- our advancing bucket
- wall bucket
- flight-time bucket
- recent direction-change bucket
- recent decel bucket

This is the movement-side counterpart to the surfer gun's simple
distance/velocity/last-velocity segmentation. The exact fields can share the
`CombatRegime` vocabulary below, but the first objective is semantic
separation: hit danger, occupancy, and expected pressure must be distinct.

### Telemetry

Add movement evidence diagnostics before behavior changes:

```text
movement.wave_pass
  evidence_kind=movement_wave_pass
  target_id
  wave_kind
  gf
  bin
  own_risk_regime

movement.hit_danger
  evidence_kind=movement_bullet_hit
  target_id
  power
  damage
  gf
  bin
  own_risk_regime
  hit_wave_error

movement.danger_breakdown
  enemy_hit_component
  flattening_component
  expected_wave_component
  total_danger
```

Existing `hit.bullet` should keep reporting whether a movement wave matched,
but add enough fields to diagnose match error and resulting danger update.

### Tests

Unit tests should verify:

- wave-pass visits update only the flattening profile
- real bullet hits update only the enemy-hit danger profile
- expected waves do not create permanent hit danger without confirmation
- candidate danger reports separate hit, flattening, and expected components
- unmatched bullet hits are visible in telemetry and do not silently corrupt
  danger tables

### Validation

Use the Python BasicGFSurfer port as the focused evidence target:

```sh
PYTHONPATH=bots .venv/bin/python -m pytest tests/test_movement_wave_evidence.py
scripts/run-battle.sh --telemetry --rounds 24 \
  bots/adaptive-prime bots/ports/basic-gf-surfer-port
tools/telemetry_audit.py battle-results/runs/<run>/telemetry \
  --require-bot adaptive-prime
tools/combat_economics_summary.py battle-results/runs/<run>
```

Success criteria:

- movement wave-match rate is reported and stable enough to trust
- surfer bullet-damage pressure can be explained by hit-danger bins/regimes
- wave-pass occupancy and real hit danger are visibly different in telemetry
- no EV/firepower behavior changes are mixed into the first patch

## Implementation Subplan: Shared Combat Regime Key

After wave evidence semantics are clean, add a shared regime vocabulary that
all guns, movement, and fire economics can use. The BasicGFSurfer port is strong
because its gun and movement are aligned around a small set of meaningful state
features. Adaptive should stop letting every subsystem describe the fight in a
different feature language.

### Purpose

Create one compact shared representation for "what kind of combat state is
this?" It should be useful for:

- gun candidate matching
- gun profile segmentation
- displacement replay scoring
- enemy-hit danger learning
- EV fire decisions
- anti-repetition movement

This is not a new tactical brain. It is a shared feature adapter.

### Simplicity Lesson From BasicGFSurfer

BasicGFSurfer is not strong because it has no features. It is strong because
its gun and movement use a small, consistent feature language. Its gun cares
about distance, velocity, last velocity, and lateral direction; its movement
learns guess-factor danger from our waves.

The shared regime key should copy that alignment property, not the exact bot.
It must be a common vocabulary with per-system adapters:

- Dynamic Cluster uses it as soft neighbor weighting.
- Traditional GF uses a compact subset as one profile source.
- Displacement uses it as replay candidate bonuses.
- Movement uses own-risk regimes for enemy-hit danger.
- Fire EV uses regime profitability/danger, not full hard buckets.
- Linear and head-on mostly ignore it.

Do not create one giant universal hard segment key. That would recreate
sparsity and make the system harder to reason about. The value is consistency
across systems, with each gun using only the subset that matches its model.

### New Shared Module

Add:

```text
bots/bot_core/combat/regime.py
```

Core structures:

```text
CombatRegime
  distance_bucket
  flight_time_bucket
  target_speed_bucket
  target_last_speed_bucket
  target_lateral_bucket
  target_advancing_bucket
  target_accel_bucket
  target_wall_bucket
  own_speed_bucket
  own_last_speed_bucket
  own_lateral_bucket
  enemy_power_bucket

CombatRegimeConfig
  distance_edges
  flight_time_edges
  speed_edges
  lateral_edges
  advancing_edges
  wall_edges
  power_edges

build_target_regime(...)
build_own_risk_regime(...)
```

Keep values coarse and stable. Start with buckets that can be inspected in
telemetry, not continuous weights hidden in each gun.

Initial bucket shape:

```text
distance: close / mid / far / very_far
flight_time: short / medium / long
speed: stopped / slow / medium / fast
last_speed: stopped / slow / medium / fast
lateral: reverse / low / medium / high
advancing: retreating / flat / advancing
wall: near / mid / open
power: low / medium / high
```

### Integration Rules

Do not force every system to hard-segment on the full regime. Each system should
use the same regime differently:

| System | First use |
| --- | --- |
| Dynamic Cluster | Soft neighbor bonus for same distance/speed/last-speed/lateral/flight-time regime. |
| Traditional GF | Experimental profile source keyed by a compact regime subset. |
| Displacement | Replay candidate bonus for same speed/last-speed/lateral/wall/flight-time regime. |
| Anti-surfer | Detect repeated post-fire movement responses by regime. |
| Movement | Record enemy-hit danger by own-risk regime. |
| EV fire gate | Ask whether current regime is profitable or dangerous. |
| Telemetry | Emit sampled regime fields for calibration and audit. |

Start with telemetry-only regime emission, then enable one consumer at a time.
The first behavior consumer should be movement hit-danger lookup, because the
wave-evidence split depends on own-risk regimes and directly addresses the
surfer damage leak. Displacement or Dynamic Cluster can consume the same regime
next as soft candidate-similarity bonuses. Traditional GF should consume the
same regime object later rather than inventing a private surfer-shaped key.

### Telemetry

Add sampled regime diagnostics to existing events before using the regime for
decisions:

```text
track:
  combat_regime
  combat_regime_distance
  combat_regime_target_speed
  combat_regime_target_last_speed
  combat_regime_lateral
  combat_regime_wall

gun.wave_visit / gun.eval_wave_visit:
  fire_context_regime

hit.bullet or combat.profile:
  own_risk_regime
```

Use readable bucket labels in telemetry. If integer buckets are needed for
speed, emit labels and ints together only after the analyzer needs both.

### Tests

Unit tests should pin bucket boundaries and symmetry:

- distance and flight-time bucket boundaries
- velocity and last-velocity buckets
- lateral/advancing sign handling
- wall bucket from wall margin
- own-risk regime includes enemy bullet-power bucket
- regime keys are hashable and stable
- missing target-motion data falls back predictably

Integration tests should verify:

- Adaptive can build a regime during aim/fire ticks.
- `gun.wave_visit` carries the regime from the fired wave.
- A forced Dynamic Cluster or Displacement run can report regime diagnostics
  without changing decisions.

### Validation

Telemetry-only run:

```sh
PYTHONPATH=bots .venv/bin/python -m pytest tests/test_combat_regime.py
scripts/run-battle.sh --telemetry --rounds 12 \
  bots/adaptive-prime bots/ports/basic-gf-surfer-port
tools/telemetry_audit.py battle-results/runs/<run>/telemetry \
  --require-bot adaptive-prime
```

Analyzer follow-up:

```sh
tools/gun_eval_summary.py battle-results/runs/<run>/telemetry --bot adaptive-prime
tools/combat_economics_summary.py battle-results/runs/<run>
```

Success criteria:

- Regime labels are stable and interpretable.
- The port matchup shows repeated regimes before enemy damage spikes.
- No behavior changes happen in the first telemetry-only patch.
- Later gun/movement experiments reuse this shared regime instead of adding
  gun-local one-off segmentation.

## Implementation Subplan: Profile And EV Fire Slice

After wave evidence and regime labels are clean, add a small shared
telemetry-first profile slice. The useful fire-side change is not another gun
threshold; it is a reliable live view of the damage exchange and a single
guarded place where fire decisions can use it.

### Evidence To Encode

The Python BasicGFSurfer port is intentionally focused:

- fixed bullet power `1.9`
- gun segmentation by distance, enemy velocity, and enemy last velocity
- one shared lateral direction
- battle-persistent GF gun stats
- surfing waves inferred from our energy drops
- hit danger learned into one surf-stat buffer

That means Adaptive should assume the port gets value from two things:

1. Adaptive repeatedly exposing similar distance/velocity/last-velocity states.
2. Adaptive firing enough weak waves to let the port surf while the port returns
   higher-value bullets.

The first implementation slice should measure those facts directly. Do not
hard-code BasicGFSurfer or add anti-surfer aiming yet.

### New Shared Runtime Object

Add a shared profile module, tentatively:

```text
bots/bot_core/combat/profile.py
```

Core structures:

```text
CombatProfileStore
  profile_for(target_id)
  record_our_fire(target_id, turn, power, aim_mode, gun_score, gun_visits)
  record_our_hit(target_id, turn, power, damage, aim_mode)
  record_enemy_fire(target_id, turn, power, confidence)
  record_enemy_hit(target_id, turn, power, damage, movement_mode, gf_bin)
  snapshot(target_id, turn)
  clear_round_state()
  clear_battle_state()

CombatProfileSnapshot
  our_shots, our_hits, our_hit_rate
  our_avg_power, our_avg_hit_power, our_damage_per_shot
  enemy_shots, enemy_hits, enemy_hit_rate
  enemy_avg_power, enemy_damage_per_shot, enemy_damage_per_hit
  rolling_damage_delta
  recent_our_hit_rate
  recent_enemy_hit_rate
  tags
```

Use small rolling windows first. A fixed-size deque per target is enough:

```text
recent our fire events: 40
recent enemy fire events: 40
recent damage events: 40
```

Keep total counters beside rolling counters so telemetry can show both lifetime
and recent signals. Do not add decay curves until simple windows fail.

Tags should be deterministic and explainable:

```text
damage_deficit:
  enemy bullet damage - our bullet damage >= configured margin

survival_lead_damage_loss:
  our energy/score shape is okay but bullet damage delta is negative

evasive_target:
  our recent hit rate below threshold after enough shots

high_pressure_enemy:
  enemy recent damage per shot or damage per hit above threshold

surfer_like_pressure:
  high_pressure_enemy and evasive_target and enemy_avg_power >= 1.5

low_energy_endgame:
  our energy below existing low-energy policy band
```

Use config defaults in shared code, then expose only a small Adaptive rollout
flag in `bots/adaptive-prime/adaptive_config.py`:

```text
ROBOCODE_ADAPTIVE_COMBAT_PROFILE=1
ROBOCODE_ADAPTIVE_EV_FIRE_GATE=0
```

The profile flag can default on once telemetry-only tests pass. The EV gate
must default off until battle validation passes.

### Adaptive Integration Points

Wire the store into Adaptive first:

| Source | Current location | Profile update |
| --- | --- | --- |
| Our requested fire | `AdaptivePrime._track_or_search()` before `set_fire()` | keep proposed shot context for the pending bullet. |
| Actual bullet fired | `AdaptivePrime.on_bullet_fired()` | `record_our_fire(...)` using actual bullet id/power and selected gun. |
| Our bullet hit | `AdaptivePrime.on_bullet_hit()` | `record_our_hit(...)` with damage, power, and stored aim mode. |
| Enemy fire detected | `AdaptivePrime._detect_enemy_fire()` after accepted drop | `record_enemy_fire(...)` with inferred power and confidence `energy_drop`. |
| Enemy bullet hit us | `AdaptivePrime.on_hit_by_bullet()` | `record_enemy_hit(...)` with bullet power, damage, movement mode if known, and movement GF/bin when wave matched. |
| Round/game reset | existing reset handlers | clear round waves, preserve battle profile only if target ids are stable for the battle; clear on game start. |

Prefer adding a small `CombatProfileStore` member to Adaptive rather than
threading profile data through unrelated classes. Once proven, move construction
into shared bot wiring for Chase/Circle/Sweep.

### Telemetry Shape

Add a sampled event instead of overloading every `track` field:

```text
combat.profile
  target
  our_shots
  our_hits
  our_hit_rate
  our_avg_power
  our_damage_per_shot
  enemy_shots
  enemy_hits
  enemy_hit_rate
  enemy_avg_power
  enemy_damage_per_shot
  rolling_damage_delta
  tags
```

Also add a compact subset to `track` only after it proves useful in the viewer:

```text
combat_tags
combat_damage_delta
combat_enemy_pressure
```

Update:

- `bots/bot_core/telemetry/schema.py`
- `bots/bot_core/telemetry/fire.py` or a new `telemetry/combat.py`
- `tools/telemetry_audit.py` tests if required fields are introduced
- `tools/combat_economics_summary.py` only if the new event enables a useful
  run-level table; do not block the profile phase on analyzer changes

### EV Fire Gate Prototype

After telemetry-only profile data is correct, add a guarded function in shared
energy/fire code, tentatively:

```text
bots/bot_core/energy/shot_value.py
```

Inputs:

```text
base FireDecision
proposed firepower
selected aim mode
selected gun confidence and visits
dynamic shot quality diagnostics when present
CombatProfileSnapshot
distance
target energy
own energy
```

Computation:

```text
damage_value = bullet_damage_for_power(firepower)
hit_estimate = blend(selected virtual score, recent real hit rate, shot quality)
shot_ev = hit_estimate * damage_value
enemy_wave_cost = pressure multiplier when tags include surfer_like_pressure
net_shot_value = shot_ev - enemy_wave_cost
```

Decision rules for the first prototype:

- Never override stale target, gun alignment, critical energy, or impossible
  energy decisions.
- Do not block finishers inside existing finisher distance.
- Do not block high-confidence shots with `firepower >= 1.3`.
- Under `surfer_like_pressure`, block weak Dynamic Cluster shots when:

```text
firepower < 1.3
net_shot_value < configured minimum
target is not a finisher
```

- Emit a reason even when allowing:

```text
ev_ready
ev_hold_low_value
ev_allow_finisher
ev_allow_good_shot
ev_disabled
```

Do not change `AimModeSelector` in this slice. If the selected gun is bad, the
profile and EV telemetry should expose it first.

### Firepower Floor Prototype

Only after the EV gate produces expected holds, add a tiny firepower floor
wrapper around Adaptive's current `_select_firepower()` result:

```text
if surfer_like_pressure and good_shot:
    firepower = max(firepower, 1.6)
elif evasive_target and good_shot:
    firepower = max(firepower, 1.3)
elif weak_shot:
    leave firepower unchanged and let EV gate hold it
```

`good_shot` should initially mean:

```text
selected gun visits >= threshold
selected gun score >= threshold
or dynamic_cluster_shot_quality >= threshold
```

This keeps the first behavior change readable: weak shots are held, good shots
are paid.

### Tests To Write First

Unit tests:

- profile records our shots, hits, damage per shot, and average power
- profile records enemy inferred fire and enemy bullet hits
- rolling metrics differ from lifetime metrics after old events fall out
- tags activate only after minimum sample counts
- short low-sample profiles do not mark `surfer_like_pressure`
- EV gate never bypasses stale/alignment/critical-energy holds
- EV gate holds weak low-power shots only under pressure tags
- EV gate allows finishers and good high-power shots
- firepower floor raises only good shots and leaves weak shots to the gate

Integration-style tests:

- Adaptive `on_bullet_fired()` and `on_bullet_hit()` update the profile through
  actual bullet ids/powers.
- `hit.bullet` with a movement wave match records enemy hit pressure and GF/bin
  context.
- `combat.profile` passes telemetry schema/audit checks.

### Validation Commands

First patch, telemetry-only:

```sh
PYTHONPATH=bots .venv/bin/python -m pytest \
  tests/test_combat_profile.py \
  tests/test_telemetry_audit.py

scripts/run-battle.sh --telemetry --rounds 12 \
  bots/adaptive-prime bots/ports/basic-gf-surfer-port

tools/telemetry_audit.py battle-results/runs/<run>/telemetry \
  --require-bot adaptive-prime
tools/combat_economics_summary.py battle-results/runs/<run>
```

Behavior patch, EV gate enabled for candidate:

```sh
scripts/run-ab.sh \
  --name adaptive-ev-fire-gate \
  --preset adaptive-1v1-basic-gf-surfer-port \
  --baseline <baseline-worktree> \
  --candidate <candidate-worktree> \
  --candidate-env ROBOCODE_ADAPTIVE_EV_FIRE_GATE=1 \
  --rounds 24 \
  --repeats 3 \
  --telemetry

tools/combat_economics_summary.py battle-results/ab/<experiment>
for telemetry in battle-results/ab/<experiment>/candidate/adaptive-vs-basic-gf-surfer-port/run-*/telemetry; do
  tools/gun_eval_summary.py "$telemetry" --bot adaptive-prime
done
```

Promotion requires better raw port economics, not filtered legacy economics:

- Adaptive score and firsts do not collapse.
- Adaptive bullet damage rises or port bullet damage falls materially.
- Adaptive average hit power rises.
- Low-power Dynamic Cluster shot count falls under pressure.
- Per-gun real conversion does not hide a broken gun behind fewer shots.
- `combat.profile` tags activate before the late-round damage deficit, not only
  after the battle is already lost.

## Phase 0: Wave Evidence Semantics

Separate wave-pass occupancy from real enemy-hit danger before adding new
economics. This is the first behavior-adjacent change because later combat
profile, EV, and movement decisions should consume clean evidence.

Implement:

- `enemy_hit_profile` for matched real bullet hits.
- `visit_flattening_profile` for ordinary enemy-wave pass visits.
- explicit evidence-kind telemetry for wave passes, hit-danger updates, and
  expected waves.
- danger breakdown fields that show hit danger separately from flattening
  pressure.

Initial implementation should preserve current movement decisions or use the
new stores only behind a guarded flag. First prove that the evidence separation
is correct and visible.

Acceptance:

- Unit tests prove each evidence kind updates only its intended store.
- `hit.bullet` and movement telemetry report wave-match status, match error,
  GF/bin, and own-risk regime.
- A 24-round port run can explain surfer bullet hits through hit-danger
  evidence without relying on wave-pass counts as the main danger signal.

## Phase 1: Shared Combat Regime Key

Add the shared regime vocabulary after evidence kinds are separated. The regime
does not need to control behavior immediately; first it should label gun visits,
movement hit danger, and future EV/profile records in the same coarse language.

Acceptance:

- Regime bucket unit tests pass.
- `track`, `gun.wave_visit`, and movement hit-danger telemetry carry readable
  regime labels.
- No gun or firepower behavior changes happen in the first regime patch.

## Phase 2: Opponent Combat Profile

Add a shared per-target combat profile that is updated from existing telemetry
events and runtime observations.

Track:

- our shots, hits, average firepower, and bullet damage by target
- our rolling hit rate and rolling damage per shot
- enemy shots inferred from energy drops
- enemy hits on us, average bullet power, and damage per hit
- score-shape signals: survival lead, bullet-damage deficit, low-energy state
- target evasiveness: low hit rate despite many shots
- enemy pressure: high enemy damage per hit or frequent hits

Derived tags:

```text
easy_target
evasive_target
high_pressure_enemy
damage_deficit
survival_lead_damage_loss
surfer_like
low_energy_endgame
```

Initial implementation should only publish profile state and telemetry. Do not
change behavior in the first patch.

Acceptance:

- `track` or a new sampled event shows profile tags and core rolling metrics.
- Unit tests cover profile updates from our fire/hit and enemy-hit events.
- A 12-round port run shows the profile identifies high enemy pressure and
  damage deficit before the final rounds.

## Phase 3: Enemy-Hit Danger Movement

Use the clean `enemy_hit_profile` from Phase 0 in movement scoring. This should
be generic, not surfer-only.

When we are hit, record the hit guess factor and own-risk regime:

- distance bucket
- our lateral velocity bucket
- our acceleration or last-velocity bucket
- wall margin bucket
- enemy bullet-power bucket
- enemy gun-heat/wave timing confidence

Movement candidate scoring then asks:

```text
if candidate lands in a historically dangerous GF region:
    add enemy_hit_danger
if candidate repeats heavily visited wave-pass regions:
    add smaller flattening penalty
```

This directly attacks the BasicGFSurfer port's focused gun shape, but it also
helps against other GF-style enemies.

Acceptance:

- Unit tests cover hit-danger update and lookup separately from flattening.
- Telemetry shows top danger bins and whether movement avoided them.
- Against the Python port, enemy bullet damage falls without relying only on
  reduced firing.

## Phase 4: Expected-Value Fire Gate

Replace "aligned enough, fire" with "shot is worth firing." This does not mean
the bot becomes passive. It means low-value shots stop training strong enemies
for free.

Compute:

```text
hit_estimate = selected_gun_confidence adjusted by recent real conversion
damage_value = bullet damage for proposed firepower
shot_ev = hit_estimate * damage_value
enemy_wave_cost = pressure-weighted cost of giving a surfer-like enemy a wave
net_shot_value = shot_ev - enemy_wave_cost
```

Behavior:

- Easy target: current fire policy mostly unchanged.
- Evasive target: require higher `net_shot_value`.
- High-pressure enemy: prefer fewer, stronger shots when confidence is good.
- Surfer-like enemy: hold weak low-power shots unless they are kill shots or
  movement/position creates a short escape window.

Acceptance:

- BasicGFSurfer port run shows fewer low-power Dynamic Cluster shots.
- Average Adaptive hit power rises without a collapse in hit rate.
- Score and bullet damage are both reported; hit rate alone is not accepted as
  success.

## Phase 5: Dynamic Firepower Floors

Once the EV gate exists, add firepower floors from opponent profile instead of
hard-coded surfer rules.

Example policy:

```text
if easy_target:
    normal adaptive firepower
elif high_pressure_enemy and good_shot:
    firepower >= 1.6
elif evasive_target and good_shot:
    firepower >= 1.3
elif evasive_target and weak_shot:
    hold or fire only for tactical low-energy reasons
```

The important rule is: good shots get paid. Weak shots do not become a stream
of low-value bullets.

Acceptance:

- Against `basic-gf-surfer-port`, Adaptive's bullet damage closes materially.
- Against local bots, firepower floors do not cause obvious survival collapse.
- Telemetry explains each floor: `easy`, `evasive_good_shot`,
  `high_pressure_good_shot`, `weak_hold`, etc.

## Phase 6: Anti-Repetition Movement Mode

When the opponent profile says the enemy is learning us, make Adaptive less
stationary in simple feature space.

Possible actions:

- vary preferred distance band
- jitter reversal timing
- avoid repeating the same velocity/last-velocity transition
- increase lateral-direction randomness near previously dangerous GF bins
- occasionally choose a lower immediate movement score to break model
  predictability

Keep this bounded. The bot should not become random all the time.

Activation:

```text
enemy_hit_rate_rising or repeated_hit_gf_bins or damage_deficit
```

Acceptance:

- Movement telemetry shows anti-repetition active only under pressure.
- Local bots do not become harder for Adaptive than before because movement is
  needlessly noisy.
- BasicGFSurfer port's bullet damage drops relative to baseline.

## Phase 7: Damage-Aware Gun Selection

The virtual gun selector should eventually rank by expected value, not only hit
score.

Do not start here. First build profile and firepower evidence. Once those exist,
add a decision layer:

```text
gun_ev = calibrated_hit_probability(mode) * damage_for_current_firepower
```

Use this for fire decisions first. Only after that should it affect sticky gun
selection.

Rules:

- Raw virtual score remains visible.
- Adjusted EV score is separate.
- Low-power high-hit modes should not automatically dominate.
- High-power shots require enough confidence.

Acceptance:

- `gun.switch_decision` reports raw score, adjusted score, firepower, and EV.
- Selector changes are explainable from telemetry.
- A forced-gun matrix still runs, so selector changes are not masking bad guns.

## Phase 8: Surfer-Algorithm Exploitation

Only after generic economics and movement danger exist, add a specialized but
still generic anti-surfer aim path.

The idea is not "shoot BasicGFSurfer." The idea is "shoot enemies whose movement
is reacting to our waves."

Approach:

- detect surfer-like behavior from enemy movement after our fire events
- simulate enemy left/right surf choices
- infer which side their danger model prefers from recent history
- aim at the likely surf destination

This can become a new `anti_surfer` implementation or a Displacement/particle
gun feature. It should not be a broad selector penalty.

Acceptance:

- Anti-surfer mode beats baseline in forced-gun runs against the Python
  BasicGFSurfer port.
- It does not fire often in ordinary selector runs unless diagnostics show
  relevant surfer-like behavior.

## Validation Matrix

Every phase that changes behavior should run the focused combat-economics gate:

```sh
PYTHONPATH=bots .venv/bin/python -m pytest
git diff --check
scripts/run-battle.sh --telemetry --rounds 24 bots/adaptive-prime bots/ports/basic-gf-surfer-port
tools/combat_economics_summary.py battle-results/runs/<run>
tools/gun_eval_summary.py battle-results/runs/<run>/telemetry --bot adaptive-prime
```

Do not include the local-bot matrix in this plan's normal loop. Chase, Circle,
and Sweep are useful smoke opponents for broad release confidence, but they are
not the evidence target for the combat-economics problem and slow iteration
without answering the main question.

Do not use legacy `basic-gf-surfer` as a normal gate. It is noisy and can
produce high-accuracy rounds that distort raw gun conclusions. Use it only when
explicitly investigating converted legacy behavior, and then report the
accuracy-filtered view as diagnostic context, not as the primary promotion
policy:

```sh
tools/combat_economics_summary.py battle-results/runs/<legacy-run> --accuracy-filter-threshold 0.30
```

Promotion gate:

```sh
scripts/run-ab.sh --name combat-economics-gate --preset adaptive-1v1-basic-gf-surfer-port --rounds 24 --repeats 3 --telemetry
tools/combat_economics_summary.py battle-results/ab/<experiment>
```

Judge using:

- raw score and firsts against the port
- bullet damage, not just survival
- our average hit power
- enemy average hit power
- our damage per shot
- enemy damage per shot
- per-gun real conversion
- movement danger-bin hit reduction

## Suggested Implementation Order

1. Split movement wave evidence into hit danger, wave-pass flattening, and
   expected-wave pressure.
2. Add shared `CombatRegime` / own-risk regime telemetry.
3. Shared `CombatProfile` in `bot_core`: telemetry-only opponent profile.
4. Fire telemetry additions: record proposed firepower, selected gun, confidence,
   shot EV inputs, and final decision reason.
5. Shared enemy-hit GF danger table for movement using the clean hit profile.
6. Shared EV fire gate in the core fire-decision path, guarded by env flag.
   Validate with Adaptive against the Python BasicGFSurfer port, then let other
   repo bots inherit the shared behavior unless a bot-specific personality
   conflict appears.
7. Shared dynamic firepower floors in the core firepower policy, with bot-local
   personality knobs only for aggression/conservation bias.
8. Anti-repetition movement mode using that danger table.
9. Damage-aware virtual gun selector.
10. Rebuild anti-surfer gun using reachable surf-choice prediction.
11. Delete or collapse old selector/fire/movement branches that are beaten by the
   shared replacement and no longer serve force testing or diagnostics.

## Success Definition

The repo bots become stronger because their decisions are better, not because
they have more math. A successful version should:

- stop losing bullet damage while winning survival
- make high-confidence hits worth more
- stop training strong surfers with weak shots
- move away from enemy-proven danger bins
- remain strong against local non-surfer bots
- explain decisions through telemetry
- leave less dead compatibility code behind than it introduces
