# Dynamic Cluster Revalidation Against the Python Surfer

## Goal

Rebuild evidence for Adaptive Prime's `dynamic_cluster` KNN gun against the
native Python `bots/ports/basic-gf-surfer-port`. Treat tuning conclusions from
the converted legacy surfer as untrusted until reproduced here.

All model experiments force `dynamic_cluster`. Live selector behavior,
Traditional GF, Displacement, and Linear are out of scope. Production defaults
stay unchanged until a forced-gun candidate wins a promotion gate.

## Experimental invariants

- opponent: `bots/ports/basic-gf-surfer-port`, never the legacy surfer;
- gun: `ROBOCODE_ADAPTIVE_GUN_MODE=dynamic_cluster`;
- eval waves off unless a run specifically validates telemetry;
- identical movement, radar, fire gate, battlefield, rounds, and repeats;
- no accuracy filtering of Python-port results;
- production visits train KNN memory across rounds in one battle;
- score and first places are guardrails, not model-ranking metrics.

## Measurement contract

Primary real-shot metrics:

- Dynamic Cluster hit rate, damage per shot, and damage per fired energy;
- shot count, average power, and power distribution;
- cold, warmup, and mature conversion.

Model metrics:

- production mean absolute and signed GF error;
- virtual hit score;
- neighbor count and distance distribution;
- density score, effective bandwidth, peak margin, and ambiguity rate;
- neighbor agreement, tag match, flight-time delta, wall-escape delta, and
  lateral confidence;
- shot-quality class and recommended/actual power.

Integrity metrics:

- telemetry audit passes;
- forced mode is reported in `bot.config`;
- no selector changes or non-Dynamic shots after KNN warmup;
- comparable shot opportunities and power when comparing aim models.

## Sequence

### Phase 0: Controls and baseline

1. Record the promoted-tree Dynamic Cluster configuration as `current`.
2. Add named experiment presets rather than accumulating code edits.
3. Add missing experiment knobs for neighbor count, minimum samples, feature
   weights/distance behavior, bins, decay, and centroid enablement.
4. Run a 24-round forced telemetry baseline against the Python surfer.
5. Run a short baseline with shot-quality power scaling disabled to separate
   aim quality from power-policy economics.

### Phase 1: Revalidate the optimization bundle

Build a simple KNN control using the same memory and normalized feature tuple:

- fixed bandwidth;
- nearest-neighbor weighting without soft context adjustments;
- maximum-density bin without ambiguity centering;
- no shot-quality power scaling.

Compare `current` and the simple control for eight rounds, then confirm the
better model in two 12-round repeats. Add back context weighting, centroid
refinement, ambiguity centering, and adaptive bandwidth one at a time.

### Phase 2: Neighbor geometry

Starting from the Phase 1 winner, screen:

- neighbor counts `9`, `17`, `25`, and `35`;
- feature ablations for distance/flight time, lateral speed, advancing
  velocity, acceleration/change age, wall margin, and firepower;
- feature-weight changes only when an ablation shows real separation;
- optional sample decay only if old samples degrade mature conversion.

Reject changes that improve virtual error without improving real conversion,
or that create poor cold-start behavior.

### Phase 3: Density extraction

Test one axis at a time:

- fixed versus hit-width-adjusted bandwidth;
- bandwidth range and base value;
- 25/31/41 density bins only if quantization is visible;
- best-bin aim versus local centroid;
- second-peak suppression;
- ambiguity centering disabled versus conservative centering.

Use six-to-eight-round screens and advance at most two candidates per axis.

### Phase 4: Context weighting

Reintroduce soft context terms individually:

- movement-tag match;
- flight-time mismatch;
- directional wall-escape mismatch;
- lateral-confidence penalty;
- context-weight clamp.

Require gains in real hit rate or damage economics across repeats. Do not keep a
context term solely because its diagnostic correlation looks plausible.

### Phase 5: Shot-quality power policy

Freeze the aim model before evaluating power scaling. Compare scaling off with
the current medium/low scales using damage per fired energy, damage per shot,
survival, and shot opportunity. Re-aiming at adjusted power must remain
side-effect-free and preserve committed selector state.

### Phase 6: Promotion

Compare one frozen candidate with the winning control in three independent
24-round repeats. Request approval before any comparison exceeding 50 total
rounds. Promote only if real conversion and damage economics improve in at
least two repeats without a material cold-start or GF-error regression.

Live selector calibration is a separate follow-up after the forced model is
settled.

## Initial command

```sh
ROBOCODE_ADAPTIVE_GUN_MODE=dynamic_cluster \
scripts/run-battle.sh --telemetry --rounds 24 \
  bots/adaptive-prime bots/ports/basic-gf-surfer-port
```

## Results so far

### Current forced baseline

The 24-round `dynamic-python-surfer-current-baseline-24` run passed telemetry
audit. Dynamic Cluster fired 1,558 shots and hit 170 (`10.91%`), with mean
power `0.62`, `0.282` damage per shot, signed GF error `-0.161`, mean absolute
GF error `0.549`, ambiguity rate `0.254`, and mean shot quality `0.047`.
The very low quality score caused the existing power policy to suppress nearly
all Dynamic shots.

### Power-policy isolation and simple control

An eight-round current-model screen with quality power scaling disabled fired
369 Dynamic shots and hit 26 (`7.05%`), at mean power `1.15`, `0.353` damage
per shot, and mean absolute GF error `0.609`. The independent short run is too
noisy to decide the power policy, but confirms that scaling materially changes
shot economics.

The matching eight-round `simple_knn` screen also disabled quality scaling and
used fixed `0.18` bandwidth, best-bin aim, no ambiguity centering, and no
context weights. It fired 359 Dynamic shots and hit 27 (`7.52%`), at mean
power `1.26`, `0.465` damage per shot, and mean absolute GF error `0.551`.
Both telemetry audits passed. This is the current most promising KNN
configuration, but it remains a screen rather than a promotion result.

The exact control is now reproducible with
`ROBOCODE_ADAPTIVE_DYNAMIC_PRESET=simple_knn`; production remains `current`.
Neighbor count, sample thresholds, blend threshold, decay half-life, minimum
effective samples, and GF bins are exposed as experiment-only env knobs.

The planned two-repeat confirmation rejected `simple_knn`. Across 24 rounds
per side with quality power scaling disabled, `current` fired 1,182 Dynamic
shots and hit 101 (`8.55%`), with `0.405` damage per shot and `0.601` mean
absolute GF error. `simple_knn` fired 1,131 and hit 83 (`7.34%`), with `0.384`
damage per shot and `0.596` mean absolute GF error. All four telemetry audits
passed. The nearly tied error but materially worse real conversion means the
simple bundle must not be promoted.

A final eight-round one-variable screen compared current neighbor count `17`
with `25`. The candidate again improved mean absolute GF error (`0.516` versus
`0.553`) and damage per shot (`0.477` versus `0.429`) while reducing hit rate
(`7.14%` versus `7.51%`). Both audits passed. Do not advance `25` neighbors on
this evidence.

Current production KNN therefore remains the most credible configuration:
`current`, 17 neighbors, and the existing context/density extractor. The next
aim experiment should retain that geometry and ablate exactly one of context
weighting, centroid refinement, ambiguity centering, or hit-width bandwidth.
Do not tune the live selector until the aim model and power policy are frozen.
