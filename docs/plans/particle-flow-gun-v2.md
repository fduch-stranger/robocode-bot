# Dedicated Particle-Flow Gun V2 Plan

This plan defines the second version of the proposed `particle_flow` gun. It is
a probabilistic, regime-aware gun controller that predicts a distribution of
physically reachable enemy futures instead of selecting one historical guess
factor.

`particle_flow` is intentionally a dedicated sticky controller, not another
always-evaluated member of the normal virtual-gun registry. When explicitly
enabled, it owns aiming for the configured round or battle and uses an internal
cheap fallback when its particle result is unavailable or weak. Normal virtual
guns are not evaluated while the dedicated controller is active.

This document intentionally excludes runtime packaging and dependency policy.
It focuses on behavior, assumptions, model design, integration, telemetry, and
validation.

## Goal

Build `particle_flow` as an experimental gun that can challenge surfers and
adaptive movers by combining:

```text
physics reachability
+ latent movement regimes
+ path probability density
+ surfer danger modeling
+ soft-minimax aim selection
+ conservative confidence and fallback
+ real conversion measurement
```

The gun should answer:

```text
given current enemy state, walls, recent movement, and our own gun history,
which aim bearing maximizes expected hit value against plausible future paths?
```

It should not answer only:

```text
which historical guess factor looked most common?
```

## Core Assumptions

The plan depends on these assumptions. Each one should be verified or made
explicit in telemetry before dedicated production use.

### Physics Assumptions

- Enemy future states must be simulated with the same Tank Royale movement
  semantics used by the battle server.
- Bullet speed and gun heat follow the shared formulas documented in
  `docs/bot-core-data-structures.md`.
- Wall behavior is not a detail. Wall margin, corner pressure, wall smoothing,
  and escape-angle asymmetry must directly affect particle futures.
- Guess factors should be computed with wall-limited positive and negative
  escape angles, not only theoretical maximum escape angle.
- A particle path can be valuable even if its endpoint is not exactly on the
  bullet arrival tick, because the bullet ray may intersect the path before or
  after the coarse endpoint.

### Opponent Assumptions

- Enemy movement is not one fixed policy. It is a mixture of latent regimes
  such as orbiting, reversing, wall bending, stop-go movement, corner escape,
  and surfer-like valley seeking.
- Regime probabilities should change online from recent observed movement.
- Against surfers, the relevant prediction is second-order: the enemy is not
  merely moving; it is choosing movement based on its estimate of our danger.
- Some enemies change phase during the battle. The model should separate early
  sparse evidence, mature evidence, and recent pressure states.
- No regime should be trusted forever. Poor observation fit and repeated real
  misses must be able to reduce diagnostic confidence or increase fallback use.

### Gun-System Assumptions

- `particle_flow` lives under `bot_core.gun.guns`, but it is invoked through a
  dedicated controller path rather than registered in the normal always-on
  virtual-gun set.
- The predictor may still produce a normal `GunBearing` so shared bearing,
  wave, fire-context, and telemetry helpers remain reusable.
- Controller choice is explicit and sticky for at least one complete round.
  Normal production defaults continue to use the existing virtual-gun system.
- When the dedicated controller is active, it computes only Particle Flow and
  its internal fallback. It does not compute `dynamic_cluster`,
  `traditional_gf`, `displacement`, or the other virtual bearings every tick.
- `dynamic_cluster` remains the production baseline. Particle Flow is compared
  with it through separate forced-controller A/B runs using the same firepower
  policy, not through continuous live selector competition.

## Dedicated Sticky Execution

The initial controller switch is explicit:

```text
ROBOCODE_ADAPTIVE_GUN_CONTROLLER=virtual
ROBOCODE_ADAPTIVE_GUN_CONTROLLER=particle_flow
```

`virtual` remains the default. With `particle_flow` selected:

```text
start round
  -> construct or retain Particle Flow battle learning
  -> keep Particle Flow as the round's aim controller
  -> use particle aim when confidence and runtime gates pass
  -> otherwise use the controller's internal linear fallback
  -> never invoke the normal virtual-gun selector during the round
```

The fallback is an implementation detail of the dedicated controller, not a
selector switch. Telemetry must distinguish `particle_flow` from
`particle_flow_fallback_linear`, while real-shot attribution remains attached
to the dedicated controller experiment.

Battle-level stickiness may be tested after round-level behavior is stable.
Automatic opponent classification or mid-round controller switching is outside
this plan.

## High-Level Algorithm

Per aim opportunity:

```text
1. Build current tactical state from AimContext and target history.
2. Update latent regime probabilities from recent observed movement.
3. Allocate particles across regimes.
4. Roll out physically reachable future paths until bullet-intercept horizon.
5. Convert path mass into candidate bearing / guess-factor hit probability.
6. Apply surfer-aware soft-minimax scoring when surfer confidence is high.
7. Apply conservative confidence and runtime gates.
8. Return the best bearing, or the internal linear fallback, plus diagnostics.
```

The first implementation may use endpoint GF density for speed, but the target
architecture is path-intersection scoring.

## Tactical State

The gun should build a compact state at fire time:

```text
target id
turn
source point
target x/y
target heading
target speed
target lateral velocity
target advancing velocity
target acceleration
target heading delta
distance
firepower
bullet speed
estimated flight time
wall margin
corner proximity
wall-limited positive escape angle
wall-limited negative escape angle
time since velocity change
time since reversal
recent reversal interval estimate
recent hit/miss pressure
recent fired guess factors
recent hit guess factors
recent particle/fallback aim source
```

The state should prefer existing `AimContext`, `FireContext`, target history,
and gun visit data. New duplicated feature extraction should be avoided unless
the existing shared context is missing a required value.

## Latent Regimes

Phase 1 starts with a deliberately small regime set:

```text
orbit_continue
orbit_reverse
stop_go
wall_bend_or_escape
flat_exploration
```

Defer finer regimes until recorded-path evidence shows that the small set
cannot represent an important motion family:

```text
corner_escape
accelerate_through
decelerate_or_stop
surfer_valley_seek
surfer_edge_bias
surfer_reverse_soon
```

Each regime defines a policy over possible future actions:

```text
target speed
turn direction
turn sharpness
reversal chance
deceleration chance
wall smoothing tendency
preferred escape side
surfer danger sensitivity
```

Regimes are hypotheses, not labels that need to match the enemy's real code.
They are useful only if they produce predictive futures.

## Regime Inference

Start with a rule-weighted Bayesian filter:

```text
new_weight(regime) =
  prior_weight(regime)
  * transition_bias(previous_top_regime, regime)
  * observation_likelihood(regime, recent_movement)
```

Then normalize weights.

Observation likelihood examples:

```text
near wall and bending parallel to wall:
  raise wall_bend / wall_escape

recent sign change in lateral velocity:
  raise orbit_reverse / surfer_reverse_soon

long stable lateral direction:
  raise orbit_continue

speed repeatedly drops near zero:
  raise stop_go / decelerate_or_stop

movement selects low-density escape after our recent shots:
  raise surfer_valley_seek

enemy tends toward max escape near walls:
  raise surfer_edge_bias
```

Regime weights should include a floor so the model does not collapse to one
confident wrong explanation too early.

## Particle Allocation

Allocate particles from regime probabilities, but reserve exploration mass:

```text
allocated(regime) =
  floor_particles_per_regime
  + proportional_particles(regime_weight)
  + exploration_particles_for_low_confidence
```

The allocation should preserve rare but dangerous branches such as reversal or
corner escape even when their current probability is modest.

Particles should be deterministic enough for reproducible A/B results. Use
stable low-discrepancy schedules or deterministic action grids before adding
random noise.

## Rollout

Each particle contains:

```text
x
y
heading
speed
regime
action_variant
weight
alive
path summary
```

For each simulated tick:

```text
1. Choose target speed and turn intent from regime/action variant.
2. Apply Tank Royale movement prediction.
3. Apply wall clipping and wall-hit consequences.
4. Update path summary.
5. Check bullet wave distance and path/ray intersection opportunities.
6. Accumulate probability mass into candidate aim scores.
```

The rollout horizon should be tied to bullet flight time with a small tolerance
window. Long-horizon uncertainty should increase entropy and reduce live
confidence.

## Density And Aim Scoring

Version 1 may score endpoint GF density:

```text
density[gf_bin] += particle_weight * kernel(endpoint_gf - bin_gf)
```

Version 2 should score candidate bearings by path intersection:

```text
score(angle) =
  sum over particles:
    particle_weight
    * hit_kernel(distance from bullet path to particle path)
    * time_alignment_weight
    * regime_confidence_weight
```

Path-intersection scoring matters because a bullet can hit a likely path even
when the final endpoint cluster is not centered on the bullet arrival tick.

Candidate bearings should be evaluated over a bounded GF grid first. Later, the
best grid region can be refined with a local continuous search.

## Surfer Danger Model

The surfer component estimates what paths the enemy may consider safe against
our gun.

Inputs:

```text
our recent fired guess factors
our recent hit guess factors
our recent miss guess factors
recent confirmed-shot aim-pressure density
enemy wall margin
enemy escape-angle asymmetry
enemy reversal timing after our shots
```

Output:

```text
surfer_danger(path)
surfer_safety(path) = 1 - normalized_danger(path)
```

The model should start simple:

```text
paths near our recent high-density aim are less likely
paths near recently hit guess factors are less likely
paths near lower historical density or opposite recent pressure are more likely
wall-impossible or high-risk movement remains unlikely even if low danger
```

This is not meant to perfectly clone the enemy surfer. It should approximate
the strategic pressure our gun creates.

## Soft-Minimax Selection

When surfer confidence is low, use expected hit probability:

```text
argmax_angle E[hit_probability(angle)]
```

When surfer confidence is high, use soft-minimax:

```text
path_weight =
  physical_probability(path)
  * behavior_probability(path)
  * surfer_response_probability(path)

surfer_response_probability(path) =
  softmax(surfer_safety(path) / temperature)

score(angle) =
  sum path_weight * hit_probability(angle, path)
```

This is more useful than hard minimax. Hard minimax assumes the enemy always
chooses the perfect dodge with perfect knowledge, which makes the gun too
pessimistic. The proposed formula is technically a Boltzmann or quantal-response
reweighting rather than strict minimax; `soft-minimax` is retained as the plan's
short label. It assumes the enemy is biased toward safer paths but still
constrained by its movement style and imperfect policy.

## Real Conversion Measurement

The dedicated controller does not need a high-cardinality online calibration
system before it can be force-tested. Real shots are too sparse to support a
cross-product of regime, wall, entropy, peak, flight-time, and GF buckets.

Record coarse, attributable evidence instead:

```text
target id
controller = particle_flow
aim source = particle_flow | particle_flow_fallback_linear
top regime
coarse distance bucket
coarse wall bucket
opportunities
real shots
real hits
damage
fired energy
virtual or wave score when available
signed GF error sum
absolute GF error sum
last updated turn
```

Use this evidence offline to compare complete dedicated-controller runs with
the Dynamic Cluster control. Do not apply residual GF correction in the first
implementation. If later evidence supports online calibration, use hierarchical
shrinkage or the shared selector-calibration work rather than introducing a
Particle-Flow-specific sparse calibrator.

## Confidence

Expose confidence as a diagnostic and internal fallback gate:

```text
confidence =
  peak_strength
  * low_entropy_factor
  * top_regime_stability
  * particle_survival_factor
  * observation_fit_factor
  * cache_freshness_factor
```

Useful telemetry fields:

```text
particle_flow_confidence
particle_flow_entropy
particle_flow_peak_probability
particle_flow_top_regime
particle_flow_top_regime_probability
particle_flow_surfer_confidence
particle_flow_soft_minimax_enabled
particle_flow_observation_fit
particle_flow_aim_source
```

Confidence should be conservative. A low-confidence particle result remains
valuable for diagnostics, but the dedicated controller should use its internal
linear fallback for the real shot.

## Cache Policy

Caching is required, but the cache key should not include raw `turn_number` as
a strict identity field. Use quantized state plus freshness:

```text
target id
quantized target x/y
quantized target heading
quantized target speed
quantized distance
firepower bucket
top regime
surfer confidence bucket
```

Reuse if:

```text
same target
cache age <= configured limit
state quantization unchanged or near unchanged
gun heat is not ready
```

Invalidate if:

```text
target changes
enemy reverses
enemy speed changes sharply
enemy hits wall
distance bucket changes
firepower bucket changes
shot is fired
regime distribution changes materially
```

The cache should store both the selected bearing and the full diagnostic
summary needed for telemetry. Dedicated mode must measure cache hit rate and
incremental aim time. Caching is an optimization, not permission to evaluate
all normal virtual guns alongside Particle Flow.

## Component Structure

Add a new package:

```text
bots/bot_core/gun/guns/particle_flow/
```

Suggested files:

```text
__init__.py
config.py
controller.py
gun.py
models.py
regimes.py
rollout.py
density.py
surfer_model.py
```

Responsibilities:

```text
config.py:
  particle counts, rollout limits, cache limits, confidence thresholds,
  fallback policy, runtime budget, and feature gates

controller.py:
  sticky lifecycle, exclusive execution, shared context/wave integration,
  runtime gate, cache ownership, and internal linear fallback

gun.py:
  particle predictor orchestration and GunBearing construction

models.py:
  tactical state, particle state, rollout result, aim result

regimes.py:
  regime definitions and Bayesian regime filter

rollout.py:
  deterministic particle allocation and physics rollout

density.py:
  GF density, path-intersection scoring, entropy, peak extraction

surfer_model.py:
  surfer danger approximation and soft-minimax path weighting
```

Shared integration should be minimal and must avoid duplicating existing
feature, wave, fire-gate, or telemetry logic:

```text
Adaptive controller wiring:
  choose virtual or particle_flow before the sticky interval begins

shared gun helpers:
  build AimContext / FireContext and attribute confirmed shots and wave visits

normal GunRegistry:
  do not register or evaluate Particle Flow in normal virtual mode

dedicated particle_flow mode:
  do not calculate normal virtual-gun bearings
```

If clean reuse requires extracting a public context or wave helper from
`VirtualGunSystem`, do that narrowly. Do not create a second implementation of
guess-factor math, wall-limited escape, fire gating, or wave resolution.

## Telemetry

Add dedicated-controller diagnostics to `gun.wave_visit` and the sampled
`gun.particle_flow` event:

```text
particle_flow_confidence
particle_flow_entropy
particle_flow_selected_gf
particle_flow_peak_probability
particle_flow_second_peak_probability
particle_flow_top_regime
particle_flow_top_regime_probability
particle_flow_second_regime
particle_flow_second_regime_probability
particle_flow_particle_count
particle_flow_rollout_ticks
particle_flow_cache_hit
particle_flow_cache_age
particle_flow_surfer_confidence
particle_flow_soft_minimax_enabled
particle_flow_observation_fit
particle_flow_aim_source
particle_flow_fallback_reason
particle_flow_aim_ms
```

Emit a sampled controller event:

```text
gun.particle_flow
```

This event should be sampled or emitted on meaningful state changes because
per-tick particle telemetry can become noisy and expensive. Existing
`bot.turn_timing` and `bot.skipped_turn` events are mandatory runtime evidence
for dedicated-controller validation.

## Rollout Plan

### Phase 0: Predictor Foundation

Before dedicated use:

```text
audit the existing Tank Royale movement predictor and tests
add only missing parity cases needed by particle actions
replay recorded target motion against simple candidate regimes
measure path coverage and observation likelihood, not only endpoint error
```

The existing shared predictor already covers speed update, speed-limited turn,
wall clipping, and wall-stop behavior. Particle Flow should reuse it rather
than building another physics implementation.

### Phase 1: Small Predictor And Sampled Shadow Density

Implement:

```text
four or five initial regimes, not the full regime catalog
32-64 deterministic paths before any larger particle budget
physics rollout
continuous wave-crossing endpoint GF KDE
confidence and entropy diagnostics
cache
sampled shadow bearing without controlling real shots
```

Success:

```text
actual target paths retain useful probability mass
wall and reversal contexts improve over simple continuation prediction
incremental p95 aim cost stays within the configured experimental budget
no additional skipped turns are attributable to the shadow predictor
selected GF distribution is explainable in telemetry
```

Stop here if the generated probability distribution is not behaviorally useful.
Physics-valid paths alone are not enough.

### Phase 2: Dedicated Sticky Controller

Allow:

```text
ROBOCODE_ADAPTIVE_GUN_CONTROLLER=particle_flow
```

Run Particle Flow exclusively for the full configured sticky interval. Keep the
normal virtual registry inactive and use the internal linear fallback when
confidence, freshness, or runtime gates fail.

Success:

```text
dedicated score does not collapse against local bots
hit rate and damage per fired energy are competitive with a separate
dynamic_cluster control on at least one surfer
fallback rate is understandable and not dominant
no added skipped-turn or control-loop instability
telemetry shows whether misses are model, physics, or confidence failures
```

### Phase 3: Path-Intersection Scoring

Replace endpoint-only selection with path-intersection candidate scoring.

Success:

```text
wave score or real conversion improves in wall and reversal contexts
confidence remains conservative
aim does not collapse to center in multi-modal distributions
runtime remains inside the dedicated-controller budget
```

### Phase 4: Surfer Soft-Minimax

Add surfer danger approximation and soft-minimax path weighting.

Success:

```text
BasicGFSurfer-style cleaned results improve versus dynamic_cluster baseline
post-hit enemy adaptation is reflected in regime/surfer diagnostics
non-surfer targets do not regress significantly
```

### Phase 5: Dedicated Production Consideration

Consider an opt-in dedicated production preset only when:

```text
repeated whole-controller A/Bs beat or complement dynamic_cluster
coarse real conversion is positive across more than one opponent type
fallback and confidence behavior remain stable
p95/p99 aim latency and skipped-turn counts are acceptable
```

Success:

```text
explicit particle_flow runs are profitable and repeatable
the virtual controller remains the normal default unless evidence supports a
deliberate default change
no battle timeout or measurable control-loop instability
```

This phase does not add automatic live selection. A future meta-controller or
opponent-specific controller choice requires its own evidence and plan.

## Validation

Use local and ported-opponent checks. Converted legacy bots are reference-only
unless the task is explicitly about legacy parity.

Minimum checks:

```text
unit tests:
  regime update normalization
  particle allocation floors
  deterministic rollout reproducibility
  internal fallback gates
  density peak selection
  path-intersection scoring

sampled shadow battle:
  Adaptive virtual controller plus sampled Particle Flow vs local bot
  Adaptive virtual controller plus sampled Particle Flow vs Python
  BasicGFSurfer port
  telemetry audit
  aim-time distribution and skipped-turn comparison

dedicated battle:
  Adaptive particle_flow controller vs local bot
  Adaptive particle_flow controller vs Python BasicGFSurfer port

A/B:
  separate forced dynamic_cluster control vs dedicated particle_flow candidate
  identical firepower and fire-gate policy on both sides
  raw combat-economics summary against Python BasicGFSurfer port
  at least 24 rounds x 3 repeats before promotion
```

Promotion should require evidence against more than one opponent type. A gun
that only exploits one broken or stuck surfer scenario should not become a
production controller. Runtime promotion also requires no material increase in
skipped turns and no unacceptable p95/p99 decision-time regression relative to
the matching control.

## Failure Modes

Expected failure modes:

```text
confident wrong regime:
  misses cluster under one top regime
  mitigation: observation-fit penalty, regime floor, internal fallback,
  phase split

flat distribution:
  entropy high and peak weak
  mitigation: internal linear fallback, retain diagnostic evidence

physics mismatch:
  endpoint paths look plausible but real visits drift
  mitigation: predictor tests and gun.fire_drift inspection

surfer over-modeling:
  soft-minimax avoids the real target and aims too defensively
  mitigation: compare with surfer weighting disabled, tune temperature only
  after the physical predictor wins

performance instability:
  aim_ms spikes or cache misses near gun-ready ticks
  mitigation: lower path count, stricter cache, gun-ready scheduling,
  internal fallback
```

## Design Constraints

- Keep formulas canonical in `docs/bot-core-data-structures.md` if they become
  shared math.
- Keep particle-flow-specific behavior inside the `particle_flow` package.
- Keep controller selection outside `AimModeSelector`; Particle Flow is not a
  continuously competing virtual-gun mode in this plan.
- Do not register Particle Flow in the normal `GunRegistry` merely to reuse the
  component interface.
- Do not compute normal virtual-gun bearings while the dedicated controller is
  active.
- Reuse shared context, physics, wave, fire-gate, and telemetry helpers.
- Do not add residual GF correction in the initial implementation.
- Do not make Particle Flow the default controller from shadow or virtual score
  alone.

## Bottom Line

`particle_flow` should be treated as a high-upside dedicated experiment:

```text
first, a small physically plausible probability-density predictor
then, an exclusive round-sticky controller with an internal fallback
then, a path-intersection controller
then, a surfer-aware soft-minimax controller
finally, an opt-in production controller if repeated A/B evidence supports it
```

The first valuable result is not the full architecture. It is evidence that a
small deterministic physical distribution predicts real movement and converts
to competitive shots within the turn budget. Path-intersection and surfer
response modeling are independent follow-up experiments, not prerequisites for
testing that foundation.
