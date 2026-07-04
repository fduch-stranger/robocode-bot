# Anti-Surfer Safety Surface Rebuild Plan

The current `anti_surfer` gun is intentionally simple: it records enemy escape
guess factors into a decayed profile and aims at the least-visited non-edge bin.
That makes it easy to inspect, but it is not enough to exploit real surfing
behavior. A rarely visited bin can be empty because it is unreachable, wall
limited, inconsistent with the enemy's current movement state, or just sparse
noise.

This plan rebuilds `anti_surfer` as a reachable safety-surface gun. The design
is Morse-inspired in the practical discrete sense: treat the guess-factor
profile as a one-dimensional danger surface, find stable valleys and gate
regions, filter by reachability, and calibrate by real shot conversion.

## Goals

1. Replace absolute emptiest-bin aiming with reachable valley or gate selection.
2. Preserve the public gun mode name `anti_surfer`.
3. Keep the implementation package-local under `bot_core.gun.guns.anti_surfer`.
4. Keep `anti_surfer` force-testable before any live-selection promotion.
5. Add diagnostics before selector or availability gates hide weak model
   behavior.
6. Treat a counterfactual surfer model as the long-term version of this gun:
   first build the reachable safety surface, then simulate what path a surfer
   would choose from that surface.

## Non-Goals

- Do not make `anti_surfer` live-selectable for Adaptive as part of the first
  rebuild step.
- Do not solve this with selector thresholds alone.
- Do not add exact high-cardinality segmentation before the global surface is
  improved.
- Do not rely on formal continuous Morse theory. The practical model is
  discrete topology over guess-factor bins.

## Baseline Problem

Current aiming is equivalent to:

```text
for bins excluding edges:
  choose the lowest profile count
  tie-break toward center
```

That fails when the selected bin is a fantasy valley:

```text
global profile says GF -0.9 is empty
current wall-limited escape says negative escape is constrained
enemy cannot plausibly reach GF -0.9
anti_surfer still shoots GF -0.9
```

The rebuilt gun should ask:

```text
where does the surfer believe it is safe,
which of those safe regions are reachable,
and where is the enemy likely forced to pass or commit?
```

## Safety Surface Model

Build a discrete danger surface across the configured guess-factor bins:

```text
danger_surface[bin] =
  smoothed historical visit density
  + optional recent aim pressure
  + optional hit pressure
  + optional model pressure
```

The first implementation should use only smoothed historical visit density and
reachability. Additional pressure terms should come later after diagnostics show
the base surface is useful.

Interpret the surface as:

```text
local minima = safe valleys
local maxima = danger ridges
basin width = how broad a safe region is
valley depth/prominence = how stable the valley is
gate = boundary or transition region between competing basins
```

## Proposed Changes

### 1. Add Surface Diagnostics First

Before changing selection behavior broadly, expose the structure the gun sees.
Keep these diagnostics component-owned through `GunBearing.metadata`,
`visit_diagnostics()`, or package-local telemetry fields if later needed.

Suggested fields:

```text
anti_surfer_selected_gf
anti_surfer_selected_bin
anti_surfer_selection_kind        # valley, gate, fallback
anti_surfer_profile_weight
anti_surfer_reachable_min_gf
anti_surfer_reachable_max_gf
anti_surfer_valley_count
anti_surfer_selected_valley_width
anti_surfer_selected_valley_depth
anti_surfer_selected_valley_prominence
anti_surfer_gate_score
anti_surfer_surface_entropy
anti_surfer_surfer_relevance
```

Expected effect:

- Make forced runs explainable.
- Separate "bad surface" from "good surface, bad selector context".
- Provide evidence before confidence gates or selector promotion.

### 2. Replace Emptiest Bin With Reachable Local Valley

Smooth the profile and find local valleys rather than isolated empty bins:

```text
smooth bins with a small symmetric kernel
find local minima below nearby basin shoulders
measure valley width, depth, and prominence
ignore one-bin holes with weak prominence
```

Filter candidates by reachability:

```text
wall-limited positive/negative escape angle
current lateral direction and lateral confidence
current speed and reversal cost
distance / bullet flight time
```

Start with wall-limited escape from `FireContext`. Add velocity and reversal-cost
approximations only after the wall mask is working.

Expected effect:

- Avoid aiming at unreachable escape factors.
- Prefer meaningful safe basins over noisy holes.
- Keep behavior understandable in diagnostics.

### 3. Add Gate Candidate Selection

When two reachable valleys compete, the surfer may need to pass through or
commit near a boundary region. These gate regions can be better shots than the
center of a valley.

Candidate gate signals:

```text
two valleys have similar safety score
gate lies between current likely GF and target valley
gate is reachable within bullet flight time
gate sits near a ridge shoulder, not an extreme edge
```

Score valley and gate candidates separately:

```text
valley_score =
  safety * reachability * width * prominence * surfer_relevance

gate_score =
  transition_probability * reachability * timing_fit * surfer_relevance
```

Choose the better calibrated candidate, but keep the first version conservative:
prefer valleys unless gate score is clearly stronger.

Expected effect:

- Exploit forced transitions instead of only final safe regions.
- Improve shots near reversals, wall bends, and split movement basins.

### 4. Add Coarse Shrinkage, Not Exact Segmentation

Anti-surfer data is sparse. Avoid exact segment profiles first. Use coarse
surface blending:

```text
global profile
coarse distance profile
coarse wall-limited profile
coarse lateral-direction profile
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

### 5. Add Soft Adversarial Pressure Terms Later

After the base surface works, add optional pressure terms:

```text
recent aim pressure:
  where our recent guns aimed

hit pressure:
  where our real bullets recently connected

model pressure:
  dynamic_cluster/traditional_gf high-density prediction regions
```

Use these as soft surface modifiers, not hard overrides. The anti-surfer should
look for reachable safety routes the enemy may choose, not blindly invert every
other gun.

Expected effect:

- Model what the surfer is likely trying to avoid.
- Exploit disagreement between normal guns and the safety surface.

### 6. Calibrate By Real Shot Conversion

Track whether selected valley and gate theories convert to real hits:

```text
target id
selection kind
distance bucket
wall bucket
surfer relevance bucket
valley width bucket
valley prominence bucket
real shots
real hits
virtual score
```

Use calibration only after passive evidence exists. The first live use should be
a confidence adjustment or component-level availability gate, not a selector
rewrite.

Expected effect:

- Lower trust in beautiful but ineffective valley/gate theories.
- Keep anti-surfer situational instead of broadly overconfident.

### 7. Add Counterfactual Surfer Simulation

After the reachable safety-surface model has useful diagnostics and forced-run
evidence, extend it into a counterfactual surfer predictor. This should remain
inside the public `anti_surfer` mode rather than becoming a separate first-pass
gun.

The question changes from:

```text
which reachable valley or gate looks useful?
```

to:

```text
if this enemy is surfing our shots, what safety surface do they see,
which reachable path would they choose,
and where will that path be when our bullet arrives?
```

Inputs:

```text
our recent aim guess factors and selected gun modes
our real hit and miss locations when attributable
anti_surfer historical escape profile
current wall-limited escape range
enemy lateral velocity and reversal cost
enemy recent movement style or Markov/topological tags, when available
```

Algorithm shape:

```text
1. Build the enemy-facing danger surface from our recent aim pressure,
   hit pressure, and historical GF density.
2. Generate reachable enemy surf path candidates over the current bullet flight
   time.
3. Score those paths as a surfer might: danger first, then wall/range/reversal
   cost.
4. Use soft adversarial reasoning: prefer plausible low-danger paths, but do
   not assume mathematically perfect surfing.
5. Aim at the predicted path endpoint or a forced gate along the path.
```

Expected effect:

- Turn anti-surfer from "shoot a safe-looking bin" into "shoot the safe-looking
  route the enemy is likely to choose".
- Preserve the safety-surface valley/gate diagnostics as the explanation layer.
- Give the gun a clear path to improve against real surfers without adding a
  separate mode.

Risks:

- Can overthink simple movers that are not surfing.
- Can amplify wrong assumptions about what danger map the enemy sees.
- Needs calibration and surfer-relevance gates before live selection.

## Implementation Sequence

1. Add surface analysis helpers and diagnostics while preserving current aim.
2. Switch aim from emptiest bin to reachable local valley.
3. Add gate candidates behind config, default off or conservative.
4. Add coarse shrinkage profiles.
5. Add optional soft pressure terms.
6. Add real-shot calibration evidence.
7. Add counterfactual surfer path simulation after the surface model is proven.
8. Revisit selector thresholds or live-selectability only after forced evidence.

## Verification

Start with unit tests for deterministic surface analysis:

```text
flat surface falls back near center
one broad valley selects the basin center
one-bin noise hole is ignored
unreachable valley is rejected
gate is detected between competing valleys
coarse surface falls back to global when sample count is low
```

Then run forced anti-surfer battles:

```sh
ROBOCODE_ADAPTIVE_GUN_MODE=anti_surfer \
  scripts/run-battle.sh --telemetry --rounds 24 \
  bots/adaptive-prime --legacy basic-gf-surfer

tools/surfer_glitch_analysis.py <run-dir>
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
filtered anti_surfer hit rate
filtered anti_surfer virtual wave average
selected valley/gate diagnostics vs hit rate
long-range virtual wave average
excluded stuck-surfer round count
telemetry audit cleanliness
```

Do not promote if improvement appears only in raw stuck-surfer score or only in
low-confidence diagnostics.

## Promotion Bar

Treat one run as exploratory. Before changing defaults or selector behavior,
confirm with at least:

```text
24 rounds x 3 repeats against BasicGFSurfer with telemetry
filtered surfer analysis
forced anti_surfer local smoke against repo bots
diagnostics showing valley/gate confidence correlates with real or virtual hits
```

The first acceptable result is not necessarily a live-selectable gun. A good
intermediate outcome is a force-testable anti-surfer that has explainable,
reachable valley choices and reliable diagnostics.

The counterfactual surfer phase has a higher bar than the base rebuild. It
should be compared against the strongest reachable-valley/gate version, not the
original emptiest-bin baseline.
