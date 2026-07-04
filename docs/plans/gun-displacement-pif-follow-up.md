# Displacement Gun PIF Follow-Up Plan

The first PIF implementation replaced world-space average displacement with
rotation-normalized replay. Filtered BasicGFSurfer telemetry showed that this is
not enough by itself: after excluding likely stuck-surfer rounds, forced
displacement fired heavily but only hit about 10%.

This follow-up should improve the gun's prediction quality before adding a
selector or availability gate. A confidence gate can reduce bad shots, but it
should be based on real replay-quality signals from a better gun, not used to
hide weak prediction math.

## Baseline Evidence

Forced Adaptive displacement run:

```text
battle-results/runs/20260704-displacement-vs-basic-gf-surfer
```

Important filtered-round observations:

```text
raw:
  24 rounds, 2348 score, 18 firsts, 19.5% accuracy

filtered by surfer_glitch_analysis.py:
  18 rounds, 1268 score, 12 firsts, 10.4% accuracy
  6 likely stuck-surfer rounds excluded

filtered displacement:
  894 shots, 92 hits, 10.3% hit rate

filtered virtual wave average:
  displacement: 0.0527
  dynamic_cluster: 0.1191
  traditional_gf: 0.0760
  linear: 0.0704

filtered displacement by distance:
  mid range: 0.0702
  long range: 0.0441
```

Interpretation: filtered performance is a gun-quality issue first. The gun
fires many low-value predictions against real surfing motion, especially at
longer range.

## Goals

1. Improve displacement prediction quality on filtered surfer rounds.
2. Keep the public mode name `displacement`.
3. Avoid selector-threshold tuning until the gun exposes better prediction
   behavior and quality diagnostics.
4. Preserve forced-gun testability.

## Non-Goals

- Do not add broad selector penalties first.
- Do not make displacement live-selectable for Adaptive as part of this plan.
- Do not tune to raw BasicGFSurfer score that includes stuck-surfer rounds.
- Do not optimize for the local repo bots if it hurts filtered surfer behavior.

## Proposed Changes

### 1. Choose Density-Best Replay Bearing

Current PIF uses the median relative bearing across usable replay endpoints.
That is robust to outliers, but it can aim between two real movement modes when
a surfer alternates or reverses.

Replace median selection with density-best selection:

```text
for each replay bearing:
  count nearby replay bearings using angular distance
  weight closer neighbors more strongly
  optionally weight by candidate similarity
choose the bearing with highest local density
return a small weighted centroid around that peak
```

Expected effect:

- Avoid aiming between split replay clusters.
- Prefer the strongest historical movement mode.
- Keep behavior deterministic and package-local.

### 2. Improve Candidate Similarity

Rotation-normalized replay means raw absolute heading should not dominate
candidate matching. A past pattern with different world heading can still be
useful if its relative movement shape matches.

Candidate scoring should emphasize:

- lateral speed relative to the firing bearing
- advancing speed relative to the firing bearing
- speed
- wall margin
- recent heading change or path curvature, if available from nearby history

Candidate scoring should reduce:

- absolute heading difference weight

Expected effect:

- More reusable rotated movement patterns.
- Better matching against surfers that repeat movement shape from different
  board headings.

### 3. Add Replay Quality Diagnostics

Before adding a hard confidence gate, emit or expose quality signals from the
gun so filtered telemetry can tell whether weak shots come from diffuse replay
clusters.

Suggested diagnostics:

```text
displacement_replay_count
displacement_candidate_score
displacement_peak_density
displacement_peak_share
displacement_bearing_spread
displacement_distance_bucket
```

These can live in `GunBearing.metadata` and `GunDecisionContext` first. Add
telemetry fields only for the signals that are useful in `gun.wave_visit` and
`bullet.fired` analysis.

Expected effect:

- Make confidence gating evidence-driven.
- Let forced-gun runs separate "bad model" from "good model, bad context".

### 4. Re-Evaluate On Filtered Surfer Rounds

Use forced displacement again:

```sh
ROBOCODE_ADAPTIVE_GUN_MODE=displacement \
  scripts/run-battle.sh --telemetry --rounds 24 \
  bots/adaptive-prime --legacy basic-gf-surfer

tools/surfer_glitch_analysis.py <run-dir>
tools/gun_eval_summary.py <run-dir>/telemetry --bot adaptive-prime
tools/telemetry_audit.py <run-dir>/telemetry --require-bot adaptive-prime
```

Judge primarily on filtered values:

```text
filtered score/round
filtered firsts/round
filtered displacement hit rate
filtered displacement virtual wave average
filtered excluded-round count
```

Raw score is secondary because stuck-surfer rounds can dominate it.

## Confidence Gate Criteria

Only add a displacement availability/confidence gate after density selection and
candidate matching are improved, and only if diagnostics show a clear cutoff.

Reasonable future gate signals:

```text
peak_share too low
bearing_spread too high
replay_count too low
best candidate score too weak
long-range and weak density
```

The first implementation of a gate should be component-level: return `None`
from `DisplacementGun.aim()` when replay quality is poor. Selector-level
penalties can come later if normal live selection needs more nuance.

## Promotion Bar

Treat one 24-round run as exploratory. Before promoting defaults or selector
behavior, confirm with at least:

```text
24 rounds x 3 repeats against BasicGFSurfer with telemetry
surfer_glitch_analysis.py filtered summary
telemetry audit clean
local forced-displacement smoke against repo bots
```

Do not promote if gains only appear in raw score and disappear after filtered
surfer analysis.
