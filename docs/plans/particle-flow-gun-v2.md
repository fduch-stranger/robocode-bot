# Particle-Flow Gun V2 Plan

This plan defines the second version of the proposed `particle_flow` virtual
gun. It is a probabilistic, regime-aware, game-theoretical gun that predicts a
distribution of physically reachable enemy futures instead of selecting one
historical guess factor.

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
+ real-hit calibration
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
explicit in telemetry before live selection.

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
- No regime should be trusted forever. Recent misses and calibration error must
  be able to reduce confidence.

### Gun-System Assumptions

- `particle_flow` is one `GunComponent` under `bot_core.gun.guns`.
- It must produce a normal `GunBearing` so existing virtual gun scoring can
  compare it with `dynamic_cluster`, `traditional_gf`, `linear`, and other
  guns.
- It should be eval-only first, force-testable second, and live-selectable only
  after virtual score, real-hit calibration, and runtime cost are acceptable.
- `dynamic_cluster` remains the primary KNN-GF gun during development.
  `particle_flow` should be added as a competing expert, not as an immediate
  replacement.

## High-Level Algorithm

Per aim opportunity:

```text
1. Build current tactical state from AimContext and target history.
2. Update latent regime probabilities from recent observed movement.
3. Allocate particles across regimes.
4. Roll out physically reachable future paths until bullet-intercept horizon.
5. Convert path mass into candidate bearing / guess-factor hit probability.
6. Apply surfer-aware soft-minimax scoring when surfer confidence is high.
7. Apply real-hit calibration correction and confidence shrinkage.
8. Return the best bearing plus diagnostics.
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
recent selected gun mode
recent fired guess factors
recent hit guess factors
```

The state should prefer existing `AimContext`, `FireContext`, target history,
and gun visit data. New duplicated feature extraction should be avoided unless
the existing shared context is missing a required value.

## Latent Regimes

Initial regimes:

```text
orbit_continue
orbit_reverse
wall_bend
wall_escape
corner_escape
stop_go
accelerate_through
decelerate_or_stop
flat_random
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
    * calibration_weight
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
our recent selected gun modes
our recent hit guess factors
our recent miss guess factors
current virtual-gun density if available
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
pessimistic. Soft-minimax assumes the enemy is biased toward safer paths but
still constrained by its movement style and imperfect policy.

## Real-Hit Calibration

Virtual score alone is not enough for this gun. The selector should not trust
beautiful particle distributions until real bullets confirm them.

Calibration buckets:

```text
target id
gun mode = particle_flow
top regime
surfer confidence bucket
distance bucket
wall margin bucket
entropy bucket
peak probability bucket
flight time bucket
selected GF side/magnitude bucket
```

Record:

```text
opportunities
real shots
real hits
virtual score sum
real hit rate
signed GF error sum
absolute GF error sum
last updated turn
```

Use calibration to:

```text
shrink confidence when real conversion is poor
apply small residual GF correction when signed error is persistent
block live selection in contexts with bad real conversion
reduce firepower when entropy is high or calibration is weak
```

Residual correction must be capped and shrunk toward zero until enough real
shots exist. Global uncapped residual correction is not allowed.

## Confidence

Expose confidence as a diagnostic and selector input:

```text
confidence =
  peak_strength
  * low_entropy_factor
  * top_regime_stability
  * particle_survival_factor
  * calibration_factor
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
particle_flow_calibration_factor
```

Confidence should be conservative. A low-confidence particle result is still
valuable for eval telemetry, but should not receive live shots by default.

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
summary needed for telemetry.

## Component Structure

Add a new package:

```text
bots/bot_core/gun/guns/particle_flow/
```

Suggested files:

```text
__init__.py
config.py
gun.py
models.py
regimes.py
rollout.py
density.py
surfer_model.py
calibration.py
```

Responsibilities:

```text
config.py:
  particle counts, rollout limits, cache limits, confidence thresholds,
  selector policy, and feature gates

gun.py:
  GunComponent implementation and orchestration

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

calibration.py:
  real-hit bucket stats, confidence shrinkage, residual correction
```

Shared integration should be minimal:

```text
bots/bot_core/gun/factory.py:
  register ParticleFlowGun as an optional component

bot configs:
  allow force mode and eval mode before live selection

VirtualGunSystem:
  no structural change expected
```

## Telemetry

Add component diagnostics to `gun.wave_visit` and `gun.eval_wave_visit`:

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
particle_flow_calibration_factor
particle_flow_residual_correction
particle_flow_aim_ms
```

Optionally emit a sampled component event:

```text
gun.particle_flow
```

This event should be sampled or emitted only when useful, because per-tick
particle telemetry can become noisy.

## Rollout Plan

### Phase 0: Predictor Foundation

Before live use:

```text
verify Tank Royale movement prediction against known engine behavior
add focused unit tests for speed update, turn limit, wall clipping, and GF math
```

The gun can be prototyped with the current predictor, but it should remain
eval-only until predictor fidelity is trusted.

### Phase 1: Eval-Only Particle Density

Implement:

```text
regime filter
deterministic particle allocation
physics rollout
endpoint GF KDE
confidence and entropy diagnostics
cache
eval-only bearing
```

Success:

```text
aim latency stays within budget
entropy and confidence correlate with virtual score
selected GF distribution is explainable in telemetry
```

### Phase 2: Force-Testable Gun

Allow:

```text
ROBOCODE_ADAPTIVE_GUN_MODE=particle_flow
```

Still keep it outside normal live selection.

Success:

```text
forced score does not collapse against local bots
forced hit rate is competitive with dynamic_cluster on at least one surfer
telemetry shows whether misses are model, physics, or confidence failures
```

### Phase 3: Path-Intersection Scoring

Replace endpoint-only selection with path-intersection candidate scoring.

Success:

```text
virtual score improves in wall and reversal contexts
confidence remains calibrated
aim does not collapse to center in multi-modal distributions
```

### Phase 4: Surfer Soft-Minimax

Add surfer danger approximation and soft-minimax path weighting.

Success:

```text
BasicGFSurfer-style cleaned results improve versus dynamic_cluster baseline
post-hit enemy adaptation is reflected in regime/surfer diagnostics
non-surfer targets do not regress significantly
```

### Phase 5: Calibrated Live Selection

Make `particle_flow` live-selectable only when:

```text
mode has enough virtual visits
real-hit calibration is not negative
confidence is above threshold
entropy is below threshold
aim latency is stable
selector score beats current gun after calibration
```

Success:

```text
selector chooses particle_flow rarely but profitably
post-switch real hit rate beats switch-time prediction floor
no battle timeout or measurable control-loop instability
```

## Validation

Use local and ported-opponent checks. Converted legacy bots are reference-only
unless the task is explicitly about legacy parity.

Minimum checks:

```text
unit tests:
  regime update normalization
  particle allocation floors
  density peak selection
  path-intersection scoring
  calibration shrinkage and capped residual correction

telemetry battle:
  eval-only Adaptive vs local bot
  eval-only Adaptive vs Python BasicGFSurfer port
  telemetry audit

forced battle:
  Adaptive forced particle_flow vs local bot
  Adaptive forced particle_flow vs Python BasicGFSurfer port

A/B:
  dynamic_cluster baseline vs particle_flow candidate
  raw combat-economics summary against Python BasicGFSurfer port
```

Promotion should require evidence against more than one opponent type. A gun
that only exploits one broken or stuck surfer scenario should not become a
default live gun.

## Failure Modes

Expected failure modes:

```text
confident wrong regime:
  misses cluster under one top regime
  mitigation: calibration shrinkage, regime floor, phase split

flat distribution:
  entropy high and peak weak
  mitigation: eval-only or low firepower, do not live-select

physics mismatch:
  endpoint paths look plausible but real visits drift
  mitigation: predictor tests and gun.fire_drift inspection

surfer over-modeling:
  soft-minimax avoids the real target and aims too defensively
  mitigation: temperature tuning, calibration, disable surfer weighting

performance instability:
  aim_ms spikes or cache misses near gun-ready ticks
  mitigation: lower particle count, stricter cache, eval interval
```

## Design Constraints

- Keep formulas canonical in `docs/bot-core-data-structures.md` if they become
  shared math.
- Keep particle-flow-specific behavior inside the `particle_flow` package.
- Do not add concrete `particle_flow` branches to `AimModeSelector`; use
  `GunModePolicy`, traits, diagnostics, and generic decision context.
- Do not make it live by default from virtual score alone.
- Do not promote global residual correction. Correction must be contextual,
  capped, and evidence-gated.

## Bottom Line

`particle_flow` should be treated as a high-upside experimental expert:

```text
first, a physically plausible probability-density gun
then, a path-intersection gun
then, a surfer-aware soft-minimax gun
finally, a calibrated live expert
```

The valuable version is not just particles plus KDE. The valuable version is
particles plus behavior weighting, surfer response modeling, path-intersection
scoring, and real-hit calibration.
