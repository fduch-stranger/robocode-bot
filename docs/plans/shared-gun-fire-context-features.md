# Shared Gun Fire-Context Feature Plan

This plan describes a shared fire-context feature upgrade for gun learning and
selection. The immediate motivation is improving `dynamic_cluster` KNN aim
quality, but the same context should be useful to `traditional_gf`,
`anti_surfer`, `displacement`, and selector confidence.

## Research Basis

Robowiki's dynamic clustering notes describe the technique as KNN over logged
firing situations: record values such as lateral velocity, advancing velocity,
and enemy distance, then find past entries closest to the current situation.
GuessFactor aiming normalizes bearing offsets by lateral direction and maximum
escape angle, while waves provide the firing-time source, bearing, bullet speed,
and resolved offset needed to learn from real movement.

The current shared gun model already has the right core structure:

- `AimContext` contains the live target state, firepower, normalized feature
  tuple, segment key, field margin, and movement-history tags.
- `GunWave` stores the fire-time feature tuple used for virtual-gun scoring and
  learner updates.
- `DynamicClusterGun` stores per-target `GunSample` records with
  `(target_id, turn, features, guess_factor)` and queries nearest historical
  samples.
- `TraditionalGfGun` and `AntiSurferGun` maintain profile samples separately,
  but could use richer context for segmentation, source trust, or diagnostics.
- `DisplacementGun` can use the same context as the starting point for
  PIF-style historical movement replay.

The problem is not that sample collection is wrong. The problem is that the
stored sample context is too thin for several guns to tell when an old firing
situation is tactically similar to the current one.

## Goals

1. Add shared fire-context fields once instead of adding component-specific
   feature forks.
2. Keep the existing feature tuple and current behavior usable while the new
   context is evaluated.
3. Let each gun opt into the context gradually.
4. Make diagnostics strong enough to explain whether new features improve aim,
   selector confidence, or only add noise.

## Non-Goals

- Do not replace the current KNN feature tuple in the first step.
- Do not discard existing per-target KNN samples during a round or battle.
- Do not change selector gates in the same experiment as sample-context
  collection.
- Do not add a kd-tree until profiling shows the bounded linear scan is a
  problem.

## Proposed Shared Context

Introduce a shared fire-context record that is attached to fire-time waves and
copied into learner samples when useful.

Suggested fields:

```text
movement_tags
bullet_flight_time
lateral_direction
lateral_speed_signed
lateral_direction_confidence
wall_margin
wall_escape_balance
positive_escape_angle
negative_escape_angle
distance_bucket
firepower_bucket
```

### Field Notes

`movement_tags`

Current tags such as `low_lateral`, `stable_velocity`, `stable_pattern`,
`nonlinear_mover`, `adaptive_mover`, and `surfer` are already computed for
selector context. Storing them on the fire-time sample lets KNN and profile guns
compare historical movement regimes directly.

`bullet_flight_time`

Distance and firepower are already present in the feature tuple, but flight time
is the tactical scale the target must dodge over. This should help KNN,
displacement replay, and profile segmentation distinguish short fast shots from
long slow shots.

`lateral_direction`, `lateral_speed_signed`, and `lateral_direction_confidence`

GuessFactor signs are normalized by lateral direction, which is correct for
most movement. Near zero lateral speed, sign can be noisy. Direction confidence
allows guns to downweight samples collected around direction ambiguity instead
of treating them as equally clean evidence.

`wall_escape_balance`, `positive_escape_angle`, and `negative_escape_angle`

The shared GF math already uses wall-limited escape angles. Storing the
fire-time escape shape lets GF-style guns distinguish open-field samples from
samples where one side was strongly constrained by a wall.

`distance_bucket` and `firepower_bucket`

These are optional coarse diagnostic fields. They should not replace continuous
features, but they make telemetry summaries easier to group.

## Component Usage

### Dynamic Cluster

Use the new context as soft neighbor weighting before changing the base feature
tuple.

Candidate weighting additions:

```text
tag_match_bonus
flight_time_mismatch_penalty
wall_escape_mismatch_penalty
lateral_confidence_penalty
```

Initial rule: never hard-filter samples. Multiply the existing neighbor weight
by context factors so the experiment is reversible and easy to compare.

Telemetry should report:

```text
dynamic_cluster_neighbor_distance
dynamic_cluster_neighbor_flight_time_spread
dynamic_cluster_neighbor_tag_match
dynamic_cluster_lateral_confidence
dynamic_cluster_density_score
```

### Traditional GF

Use the context for diagnostics first, then profile-source policy only if the
diagnostics justify it.

Possible uses:

- Add flight-time and wall-escape diagnostics to `gun.traditional_gf_profile`.
- Test a coarse profile key that includes flight-time bucket or escape-balance
  bucket.
- Penalize global-only profile source less when current context matches stable
  historical movement, and more when context is ambiguous.

Avoid changing source penalties and profile keys in the same experiment.

### Anti-Surfer

Use movement tags and wall-escape context to decide whether surfer-biased
anti-surfer profile evidence is relevant. This should stay opt-in because
anti-surfer is situational and easy to over-promote.

### Displacement

Use the same fire context as the matching key for PIF-style replay:

- match historical starts by movement tags
- prefer similar bullet flight time
- prefer similar wall margin and escape balance
- handle lateral-direction ambiguity explicitly

This complements the displacement PIF plan rather than replacing it.

### Linear

Linear does not need richer samples, but selector confidence can use the same
context. Stable velocity, low lateral motion, and short flight time support
linear; nonlinear/adaptive tags and low lateral-confidence direction changes
should weaken it.

## Implementation Plan

1. Add a small shared fire-context data structure in `bot_core.gun.models` or a
   nearby shared gun module.
2. Build that context alongside the existing feature tuple when creating
   `AimContext`.
3. Store the context on `GunWave` or in `GunWave.gun_metadata` so resolved
   visits can copy fire-time values into component learners.
4. Extend `GunSample` with optional context fields while keeping the existing
   constructor pattern backward-compatible for tests.
5. Populate `DynamicClusterGun` samples from production `GunVisit` values.
6. Add component diagnostics without changing aim behavior.
7. Enable dynamic-cluster soft neighbor weighting behind config defaults.
8. Only after KNN evidence is positive, test Traditional GF or displacement
   consumers independently.

## Validation Plan

Baseline before code changes:

```sh
scripts/run-battle.sh --telemetry --rounds 1 bots/adaptive-prime bots/chase-lock
tools/gun_eval_summary.py battle-results/runs/<run>/telemetry --bot adaptive-prime
scripts/run-ab.sh --name gun-context-baseline --preset adaptive-1v1-core --rounds 12 --repeats 2
```

Unit tests:

```sh
PYTHONPATH=bots .venv/bin/python -m pytest tests/test_gun_stats.py tests/test_gun_prediction.py
```

Behavior checks:

```sh
scripts/run-battle.sh --rounds 1 bots/adaptive-prime bots/chase-lock
scripts/run-battle.sh --telemetry --rounds 1 bots/adaptive-prime bots/chase-lock
tools/telemetry_audit.py battle-results/runs/<run>/telemetry --require-bot adaptive-prime
tools/gun_eval_summary.py battle-results/runs/<run>/telemetry --bot adaptive-prime
```

A/B promotion gates:

```sh
scripts/run-ab.sh --name gun-context-knn --preset adaptive-1v1-core --rounds 12 --repeats 2
scripts/run-ab.sh --name gun-context-knn-promote --preset adaptive-1v1-core --rounds 24 --repeats 3
```

Boss-bot checks, when legacy bots are configured:

```sh
scripts/run-battle.sh --rounds 1 bots/adaptive-prime --legacy basic-gf-surfer
scripts/run-ab.sh --name gun-context-boss --preset adaptive-1v1-boss --rounds 12 --repeats 2
```

## Success Criteria

- Dynamic-cluster forced-gun hit rate or virtual-wave score improves without a
  material score regression in local 1v1 A/B runs.
- Neighbor diagnostics show tighter context matches, not only more aggressive
  weighting.
- Selector telemetry does not show new churn caused by context-only changes.
- Telemetry audit remains clean.
- If Traditional GF or displacement consumes the context later, each consumer
  has its own A/B result instead of borrowing the KNN result.

## Risks

- Extra features can overfit short battles or specific local opponents.
- Lateral-direction confidence can suppress useful reversal samples if tuned too
  harshly.
- Wall-escape context may duplicate existing wall-margin signal unless the
  diagnostics prove it adds separate information.
- Adding context to shared models touches many tests and telemetry surfaces, so
  the first implementation should be narrow and backward-compatible.

## Recommended First Experiment

Start with dynamic-cluster diagnostics plus soft neighbor weighting:

```text
existing_weight
  * tag_match_factor
  * flight_time_factor
  * wall_escape_factor
  * lateral_confidence_factor
```

Keep all factors near neutral at first, emit diagnostics, and compare forced
`dynamic_cluster` runs before changing selector thresholds or other guns.
