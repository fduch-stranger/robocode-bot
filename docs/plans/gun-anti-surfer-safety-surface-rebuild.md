# Anti-Surfer Safety Surface Rebuild Plan

The current `anti_surfer` gun is intentionally simple: it records enemy escape
guess factors into a decayed profile and aims at the least-visited non-edge bin.
That makes it easy to inspect, but it is not enough to exploit real surfing
behavior. A rarely visited bin can be empty because it is unreachable, wall
limited, inconsistent with the enemy's current movement state, or just sparse
noise.

This plan rebuilds `anti_surfer` as a reachable safety-surface gun. It separates
the pressure our confirmed shots teach the enemy from the places the enemy
actually visits. The design treats those as two distinct one-dimensional
guess-factor surfaces, tests whether pressure avoidance is observable, and only
then aims at physically plausible safety regions.

## Goals

1. Replace absolute emptiest-occupancy-bin aiming with a pressure-derived,
   reachable safety selection.
2. Preserve the public gun mode name `anti_surfer`.
3. Keep the implementation package-local under `bot_core.gun.guns.anti_surfer`.
4. Keep `anti_surfer` force-testable before any live-selection promotion.
5. Add diagnostics before selector or availability gates hide weak model
   behavior.
6. Falsify or support the core surfer-response hypothesis with passive evidence
   before changing real aim.
7. Keep gun-pressure history separate from target-occupancy history.

## Non-Goals

- Do not make `anti_surfer` live-selectable for Adaptive as part of the first
  rebuild step.
- Do not solve this with selector thresholds alone.
- Do not add exact high-cardinality segmentation before the global surface is
  improved.
- Do not rely on formal continuous Morse theory. The practical model is
  discrete topology over guess-factor bins.
- Do not implement counterfactual path simulation or time-indexed gate
  interception here. Those belong to the
  [Dedicated Particle-Flow Gun V2](particle-flow-gun-v2.md) controller if its
  physical predictor reaches that phase.

## Baseline Problem

Current learning and aiming are equivalent to:

```text
record where the enemy actually visits
for bins excluding edges:
  choose the lowest enemy-occupancy count
  tie-break toward center
```

That conflates two different quantities:

```text
target occupancy:
  where the enemy actually moved when our wave arrived

gun pressure:
  where our confirmed real shots aimed and where hits taught the enemy danger
```

A surfer reacts primarily to the second quantity. Inverting target occupancy
can select a bin that is empty because it is unreachable or behaviorally
implausible, not because the enemy considers it safe:

```text
target-occupancy profile says GF -0.9 is empty
the enemy cannot plausibly reach or transition toward GF -0.9 now
anti_surfer still shoots GF -0.9
```

The rebuilt gun should ask:

```text
what gun-pressure surface have our confirmed shots exposed,
does this enemy measurably avoid that pressure,
which low-pressure regions are kinematically reachable now,
and which reachable region is behaviorally plausible at intercept time?
```

## Safety Surface Model

Build two discrete surfaces across the configured guess-factor bins:

```text
gun_pressure_surface[bin] =
  smoothed confirmed-shot aim density
  + hit pressure
  + optional model pressure

target_occupancy_surface[bin] =
  smoothed actual wave-visit density
```

`gun_pressure_surface` approximates what our firing history may teach a surfer.
`target_occupancy_surface` describes observed behavior and helps validate the
avoidance hypothesis. Do not relabel occupancy as danger or invert it directly.

The first implementation should use confirmed-shot aim density as the pressure
base and actual visits as passive response evidence. Hit pressure and other-gun
model pressure should remain optional until the base relationship is visible.

Interpret the surface as:

```text
local gun-pressure minima = candidate safe valleys
local gun-pressure maxima = danger ridges
basin width = how broad a safe region is
valley depth/prominence = how stable the valley is
occupancy response = whether later target visits shift away from pressure
```

Static GF topology does not prove that an enemy must cross a basin boundary at
the bullet-intercept tick. Gate interception is therefore not part of the base
safety-surface gun.

## Proposed Changes

### 1. Add Passive Pressure And Avoidance Diagnostics First

Before changing selection behavior, record the two surfaces separately and
test the core hypothesis: does this opponent subsequently move away from the
pressure exposed by our confirmed shots?

Pressure insertion must use the actual confirmed bullet bearing and power from
the fired-shot lifecycle, not a speculative pre-fire aim that may later be
changed or never fired. Occupancy insertion continues to use resolved wave
visits.

Keep diagnostics component-owned through `GunBearing.metadata`,
`visit_diagnostics()`, or a sampled package-local telemetry event.

Suggested fields:

```text
anti_surfer_selected_gf
anti_surfer_selected_bin
anti_surfer_selection_kind        # pressure_valley, fallback
anti_surfer_pressure_weight
anti_surfer_occupancy_weight
anti_surfer_pressure_at_visit
anti_surfer_pressure_occupancy_correlation
anti_surfer_post_pressure_shift
anti_surfer_avoidance_confidence
anti_surfer_reachable_mass
anti_surfer_valley_count
anti_surfer_selected_valley_width
anti_surfer_selected_valley_depth
anti_surfer_selected_valley_prominence
anti_surfer_pressure_entropy
anti_surfer_occupancy_entropy
anti_surfer_surfer_relevance
```

Expected effect:

- Establish whether BasicGFSurfer and other targets exhibit a measurable
  pressure-avoidance signature.
- Separate "no surfer response" from "useful response, bad reachability" and
  from selector context.
- Provide a stop gate before any aim behavior changes.

Stop or redesign the gun if mature evidence does not show a repeatable avoidance
relationship. Do not proceed merely because the pressure surface looks
interesting.

### 2. Replace Emptiest Occupancy Bin With Reachable Pressure Valley

After Phase 1 supports the avoidance hypothesis, smooth the gun-pressure surface
and find local valleys rather than isolated empty bins:

```text
smooth bins with a small symmetric kernel
find local minima below nearby basin shoulders
measure valley width, depth, and prominence
ignore one-bin holes with weak prominence
```

Score candidates by kinematic reachability and transition plausibility:

```text
current lateral direction and lateral confidence
current speed and reversal cost
distance / bullet flight time
wall-limited positive/negative escape geometry
optional low-weight occupancy plausibility after shrinkage
```

Wall-limited escape angles already define the positive and negative GF scale in
the shared wave math. They are useful geometry inputs, but by themselves they
do not make an interior GF bin reachable or unreachable. The first behavioral
version must therefore include current velocity, reversal cost, and flight time
instead of starting with a wall-only mask.

Initial candidate shape:

```text
surfer_safety = inverse_smoothed(gun_pressure_surface)

candidate_score =
  surfer_safety
  * kinematic_reachability
  * transition_likelihood
  * conservative_surfer_relevance
```

Treat occupancy as validation and, later, a softly shrunk plausibility input.
Do not invert occupancy or let a mature global occupancy profile override
current kinematics.

Expected effect:

- Avoid aiming at unreachable escape factors.
- Prefer meaningful safe basins over noisy holes.
- Keep behavior understandable in diagnostics.

### 3. Validate The Reachable-Valley Gun In Isolation

Force-test the reachable pressure-valley behavior before adding more surface
terms, segmentation, selector gates, or path simulation. Compare it with both
the current emptiest-occupancy baseline and the production Dynamic Cluster
control using identical firepower policy.

Required questions:

```text
does the selected pressure valley receive later target occupancy?
does kinematic reachability reject fantasy valleys?
does avoidance confidence correlate with virtual and real conversion?
does the gun add conditional value in wall or reversal contexts?
```

If the rebuilt gun cannot clearly beat the current anti-surfer baseline, stop.
If it improves anti-surfer but remains globally weaker than Dynamic Cluster,
keep it force-testable and evaluate only whether it offers distinct conditional
value.

### 4. Add Coarse Shrinkage, Not Exact Segmentation

Anti-surfer data is sparse. Avoid exact segment profiles first. Use coarse
surface blending:

```text
global gun-pressure surface
coarse pressure surface by distance
coarse pressure surface by wall context
coarse pressure surface by lateral-direction context

global target-occupancy surface for diagnostics
matching coarse occupancy surfaces only after enough response evidence
```

Blend with empirical-Bayes-style shrinkage:

```text
surface = global * (1 - trust) + coarse * trust
trust = f(coarse_sample_count)
```

Potential coarse contexts:

```text
distance bucket
wall escape balance bucket
lateral direction confidence bucket
surfer relevance bucket
```

Expected effect:

- Let wall and distance context shape valleys without making every context
  sample-starved.
- Keep global behavior as a stable fallback.

### 5. Add Optional Pressure Terms Later

Confirmed-shot aim density is the mandatory base pressure. After it predicts a
real avoidance response, add optional modifiers one at a time:

```text
hit pressure:
  where our real bullets recently connected

model pressure:
  dynamic_cluster/traditional_gf high-density prediction regions

recency pressure:
  short-horizon emphasis within confirmed fired aims
```

Use these as soft surface modifiers, not hard overrides. Model pressure is not
observable proof of what the enemy has learned, so it must not replace
confirmed-shot pressure.

Expected effect:

- Model what the surfer is likely trying to avoid.
- Exploit disagreement between normal guns and the safety surface.

### 6. Measure Coarse Real Shot Conversion

Track whether pressure-valley and fallback shots convert to real hits:

```text
target id
aim source = pressure_valley | fallback
coarse distance bucket
coarse wall bucket
real shots
real hits
damage
fired energy
virtual score
```

Use this evidence offline after passive and forced evidence exists. Do not build
an online cross-product of selection kind, distance, wall, relevance, valley
width, and prominence; real shots are too sparse. Any later online calibration
should use shared hierarchical calibration rather than an anti-surfer-specific
sparse store.

Expected effect:

- Lower trust in beautiful but ineffective pressure-valley theories.
- Keep anti-surfer situational instead of broadly overconfident.

### 7. Hand Off Time-Indexed Counterfactual Simulation

Do not add a second path simulator inside `anti_surfer`. If the dedicated
Particle Flow controller reaches its surfer-response phase, the validated
gun-pressure/safety surface can be considered as an input to that experiment.
Particle Flow owns time-indexed paths, regime inference, and path-intersection
scoring; `anti_surfer` remains the lightweight pressure-surface gun.

Keep the boundary explicit:

```text
anti_surfer:
  confirmed-shot pressure surface
  passive avoidance evidence
  cheap kinematic safety-valley aim

particle_flow, if validated:
  physical future paths
  latent movement regimes
  counterfactual surfer response over time
  path-intersection aim
```

Do not extract a shared abstraction until one implementation has produced
useful evidence. The plan establishes ownership now to prevent two speculative
simulators from evolving independently.

## Implementation Sequence

1. Record confirmed-shot gun pressure and resolved target occupancy in separate
   profiles while preserving current aim.
2. Add passive avoidance diagnostics and test the pressure-response hypothesis
   against BasicGFSurfer and non-surfer controls.
3. Stop or redesign if mature evidence shows no repeatable avoidance response.
4. Add kinematic reachability and pressure-valley selection behind an
   experiment flag; keep the mode force-testable only.
5. Compare the candidate with the current emptiest-occupancy anti-surfer and a
   forced Dynamic Cluster control using identical firepower policy.
6. Add coarse shrinkage profiles only after the global pressure surface wins.
7. Add hit, model, or recency pressure one at a time behind independent flags.
8. Add coarse offline real-conversion evidence.
9. Revisit selector thresholds or live-selectability only after repeated forced
   evidence. Do not add gate/path simulation in this plan.

Suggested isolated aim-policy flag:

```text
ROBOCODE_ADAPTIVE_ANTI_SURFER_SURFACE=occupancy_baseline|pressure_valley
```

This flag changes anti-surfer aim policy only. It must not change firepower,
fire gating, or opponent configuration in the matching A/B.

## Verification

Start with unit tests for deterministic surface analysis:

```text
confirmed fired aim updates gun pressure
speculative or unfired aim does not update gun pressure
resolved wave visit updates occupancy but not gun pressure
flat gun-pressure surface falls back near center
one broad low-pressure valley selects the basin center when reachable
one-bin noise hole is ignored
empty occupancy bin is not treated as a safe valley
reversal cost and flight time reject an unreachable pressure valley
wall geometry uses the shared asymmetric GF scale
coarse pressure surface falls back to global when sample count is low
```

First run passive telemetry with current aim unchanged:

```sh
scripts/run-battle.sh --telemetry --rounds 24 \
  bots/adaptive-prime bots/ports/basic-gf-surfer-port

tools/telemetry_audit.py <run-dir>/telemetry --require-bot adaptive-prime
```

Require an avoidance report that compares pressure at subsequent visits,
pressure/occupancy correlation, post-pressure GF shifts, and the same measures
against at least one non-surfer control.

Then run forced candidate battles:

```sh
ROBOCODE_ADAPTIVE_GUN_MODE=anti_surfer \
  scripts/run-battle.sh --telemetry --rounds 24 \
  bots/adaptive-prime bots/ports/basic-gf-surfer-port

tools/combat_economics_summary.py <run-dir>
tools/gun_eval_summary.py <run-dir>/telemetry --bot adaptive-prime
tools/telemetry_audit.py <run-dir>/telemetry --require-bot adaptive-prime
```

Also run local smoke battles against repo bots to catch obvious regressions:

```sh
ROBOCODE_ADAPTIVE_GUN_MODE=anti_surfer \
  scripts/run-battle.sh --rounds 8 bots/adaptive-prime bots/chase-lock
```

Judge primarily on:

```text
pressure-at-visit response after confirmed shots
pressure/occupancy relationship and post-pressure shift
avoidance confidence against surfer and non-surfer controls
filtered anti_surfer hit rate
filtered anti_surfer virtual wave average
damage per fired energy
selected pressure-valley diagnostics vs later occupancy and hit rate
kinematic fallback rate
long-range virtual wave average
excluded stuck-surfer round count
telemetry audit cleanliness
```

Do not change aim if the passive avoidance signature is absent. Do not promote
if improvement appears only in raw stuck-surfer score, only against the current
broken anti-surfer baseline, or only in low-confidence diagnostics.

## Promotion Bar

Treat one run as exploratory. Before changing defaults or selector behavior,
confirm with at least:

```text
24 rounds x 3 repeats against BasicGFSurfer with telemetry
filtered surfer analysis
forced anti_surfer local smoke against repo bots
passive evidence showing a repeatable pressure-avoidance response
diagnostics showing pressure-valley confidence correlates with later occupancy
and real or virtual hits
matching-firepower comparison with the current anti-surfer baseline and forced
Dynamic Cluster control
```

The first acceptable result is not necessarily a live-selectable gun. A good
intermediate outcome is a force-testable anti-surfer that has explainable,
reachable pressure-valley choices and reliable diagnostics. Time-indexed
counterfactual surfing remains owned by the dedicated Particle Flow plan and is
not an anti-surfer promotion step.
