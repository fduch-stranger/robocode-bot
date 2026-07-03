# Dynamic Cluster Aim Refinement Plan

This plan assumes shared fire-context features have already been collected and
validated. The goal is to improve how `dynamic_cluster` turns KNN neighbors into
an aim bearing, without bundling those changes with sample-collection or
selector-gate changes.

## Starting Point

The current dynamic-cluster gun flow is:

```text
current fire context
  -> target-specific KNN samples
  -> nearest neighbors by feature distance
  -> weighted guess-factor density over discrete bins
  -> best guess-factor bin
  -> guess-factor aim bearing
```

After the shared fire-context feature work, KNN should have richer neighbor
metadata such as movement tags, bullet flight time, wall-escape shape, and
lateral-direction confidence. The next improvement is not more collection. It
is better aim extraction from the selected evidence.

## Goals

1. Reduce quantization error from discrete guess-factor bins.
2. Make KNN aim confidence explicit and usable by telemetry, fire gates, and
   selector policy.
3. Adapt smoothing to target distance and bullet hit width.
4. Avoid overcommitting to weak or ambiguous density peaks.
5. Validate forced `dynamic_cluster` aim quality before changing live selector
   behavior.

## Non-Goals

- Do not change sample collection in this plan.
- Do not change live selector thresholds until forced-KNN evidence improves.
- Do not replace the existing KNN memory with a kd-tree unless profiling shows
  search cost is limiting bot performance.
- Do not tune other guns in the same experiment.

## Step 1: Add Aim Diagnostics

Before changing aim output, report enough data to explain KNN decisions.

Suggested diagnostics:

```text
dynamic_cluster_neighbor_count
dynamic_cluster_avg_neighbor_distance
dynamic_cluster_neighbor_distance_min
dynamic_cluster_neighbor_distance_max
dynamic_cluster_tag_match_ratio
dynamic_cluster_avg_flight_time_delta
dynamic_cluster_avg_wall_escape_delta
dynamic_cluster_avg_lateral_confidence
dynamic_cluster_density_score
dynamic_cluster_peak_margin
dynamic_cluster_neighbor_agreement
dynamic_cluster_selected_guess_factor
```

Use these fields in `gun.wave_visit`, `gun.eval_wave_visit`, or
component-owned diagnostic metadata. Keep the first diagnostics pass behavior
neutral.

## Step 2: Replace Best Bin With Local Peak Centroid

Current behavior picks the center of the best density bin. That creates
avoidable quantization error, especially when the true density peak falls
between bins.

New behavior:

```text
1. Score the same guess-factor bins as today.
2. Find the highest-scoring bin.
3. Build a local window around that bin.
4. Return the weighted centroid of samples or scored bins inside that window.
5. Clamp the result to [-1, 1].
```

This preserves the existing density model while returning a smoother aim point.

Initial centroid window:

```text
max(config.bandwidth, 1.5 * bin_width)
```

Fallback:

```text
if local centroid weight is too low:
  use the old best-bin guess factor
```

## Step 3: Add Hit-Width-Aware Bandwidth

The same GF bandwidth is not equally appropriate at all distances. Close
targets have wider angular hit windows; far targets require sharper aim.

Use hit width to adjust smoothing:

```text
hit_angle = atan2(bot_half_width, target_distance)
gf_hit_width = hit_angle / max_escape_angle
effective_bandwidth = clamp(
  max(config.bandwidth_min, gf_hit_width * bandwidth_scale),
  config.bandwidth_min,
  config.bandwidth_max,
)
```

Expected behavior:

- close range: smoother density, less overfitting
- long range: sharper density, less broad averaging

Add this behind config and report `effective_bandwidth` in diagnostics.

## Step 4: Compute KNN Aim Confidence

Add a component-owned confidence score separate from selector score.

Candidate inputs:

```text
sample_maturity = clamp(sample_count / mature_samples, 0, 1)
neighbor_quality = 1 - clamp(avg_neighbor_distance / max_useful_distance, 0, 1)
peak_margin = best_density_score - second_density_score
agreement = share of neighbor weight near selected GF
context_match = weighted tag/flight-time/wall-context match
```

Example:

```text
confidence =
  sample_maturity
  * neighbor_quality
  * clamp(peak_margin / margin_reference, 0, 1)
  * agreement
  * context_match
```

The confidence should start as telemetry only. Later it can feed firepower,
fire gating, or selector decision context.

## Step 5: Handle Ambiguous Peaks

KNN density can be multimodal. A single narrow best peak can be less reliable
than a broader second peak if the neighbor context is noisy.

Add peak diagnostics:

```text
best_peak_gf
best_peak_score
second_peak_gf
second_peak_score
peak_separation
peak_score_ratio
```

Initial behavior:

- do not blend peaks yet
- report ambiguity when the second peak is close to the first

Later behavior, only if telemetry supports it:

```text
if peaks are close and confidence is low:
  pull selected GF toward the weighted mean
or:
  pull selected GF toward 0
or:
  reduce aim confidence and let selector/fire gate react
```

## Step 6: Confidence-Aware Aim Guard

After confidence diagnostics are validated, add a conservative aim guard.

Options:

```text
low confidence -> keep selected GF but lower decision confidence
very low confidence -> blend GF toward 0
very low confidence with strong linear context -> let selector prefer linear
```

Do not start with hard unavailability unless telemetry shows clearly bad KNN
aims. Marking KNN unavailable changes selector behavior and sample exposure.

## Step 7: Multi-View Density, If Needed

If one distance metric remains unstable after centroid and confidence work,
split KNN evidence into multiple density views:

```text
base motion view
flight-time/wall view
recent-adaptation view
surfer-context view
```

Each view returns a GF density. Blend densities by view confidence, then apply
the same peak-centroid selection. This should be a later experiment because it
adds tuning surface.

## Validation

Unit tests:

```sh
PYTHONPATH=bots .venv/bin/python -m pytest tests/test_gun_stats.py tests/test_gun_prediction.py
```

Smoke:

```sh
scripts/run-battle.sh --rounds 1 bots/adaptive-prime bots/chase-lock
scripts/run-battle.sh --telemetry --rounds 1 bots/adaptive-prime bots/chase-lock
tools/telemetry_audit.py battle-results/runs/<run>/telemetry --require-bot adaptive-prime
tools/gun_eval_summary.py battle-results/runs/<run>/telemetry --bot adaptive-prime
```

Forced-KNN exploratory check:

```sh
ROBOCODE_ADAPTIVE_GUN_MODE=dynamic_cluster \
  scripts/run-ab.sh --name knn-aim-refine-forced --preset adaptive-1v1-core --rounds 12 --repeats 2
```

Promotion check:

```sh
ROBOCODE_ADAPTIVE_GUN_MODE=dynamic_cluster \
  scripts/run-ab.sh --name knn-aim-refine-forced-promote --preset adaptive-1v1-core --rounds 24 --repeats 3
```

Live selector check, only after forced-KNN improves:

```sh
scripts/run-ab.sh --name knn-aim-refine-live --preset adaptive-1v1-core --rounds 24 --repeats 3
```

Boss-bot check, when legacy bots are configured:

```sh
ROBOCODE_ADAPTIVE_GUN_MODE=dynamic_cluster \
  scripts/run-battle.sh --rounds 1 bots/adaptive-prime --legacy basic-gf-surfer
```

## Success Criteria

- Forced `dynamic_cluster` improves hit rate, virtual-wave score, or selected
  GF error without a material score regression.
- Peak-centroid output reduces average absolute aim error compared with best-bin
  output in telemetry.
- Confidence correlates with later hit quality or wave score.
- Live selector behavior does not churn more after confidence is introduced.
- Telemetry audit stays clean.

## Recommended First Implementation

Implement only:

```text
best-bin density -> local peak centroid
diagnostics for density score, peak margin, neighbor agreement, selected GF
```

Keep bandwidth, selector policy, and fire gates unchanged. This gives a narrow,
high-signal A/B test of whether aim extraction improved before adding more
tuning surface.
