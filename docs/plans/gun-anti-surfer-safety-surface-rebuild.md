# Anti-Surfer Hit-Danger Safety Surface Rebuild Plan

The current `anti_surfer` gun records resolved enemy guess-factor visits in one
decayed profile and aims at the least-visited non-edge bin. That is inspectable,
but an empty occupancy bin can be unreachable, wall-limited, inconsistent with
the enemy's current movement, or merely sparse noise.

The supported Python BasicGFSurfer benchmark also establishes an important
causal constraint: its surfing danger statistics are updated when it is hit,
not whenever the opponent fires. Confirmed fired aims therefore describe our
shot exposure, but real hit locations are the primary observable proxy for what
this benchmark has learned as danger.

This plan rebuilds `anti_surfer` around a hit-derived danger surface, while
keeping confirmed-shot exposure and target occupancy as separate evidence. It
first tests whether later movement avoids historical hit danger and only then
enables a kinematically reachable low-danger-valley aim policy.

## Goals

1. Replace absolute emptiest-occupancy-bin aiming with a reachable low-danger
   valley derived from real hit locations.
2. Preserve the public gun mode name `anti_surfer` and the current occupancy
   behavior as an experiment baseline.
3. Learn from real shots and hits produced by every gun mode, because the enemy
   observes the bot's complete firing history.
4. Keep hit danger, confirmed-shot exposure, and target occupancy in separate
   profiles with distinct telemetry semantics.
5. Falsify or support the hit-danger-avoidance hypothesis before changing real
   aim.
6. Keep the candidate force-testable and unavailable to normal live selection
   until repeated isolated evidence supports promotion.
7. Use the shared gun lifecycle only for generic confirmed-shot and shot-outcome
   delivery; keep surface analysis and policy under
   `bot_core.gun.guns.anti_surfer`.
8. Put Adaptive experiment settings in centralized Adaptive configuration and
   include them in the effective `bot.config` snapshot and fingerprint.

## Non-Goals

- Do not make `anti_surfer` live-selectable during the rebuild.
- Do not change firepower, fire gating, movement, radar, or selector thresholds
  in the matching experiment.
- Do not treat confirmed-shot aim density as learned danger for the Python
  BasicGFSurfer port.
- Do not add exact high-cardinality segmentation or an online calibration
  store.
- Do not add counterfactual path simulation or time-indexed gate interception.
  Those remain owned by the
  [Dedicated Particle-Flow Gun V2](particle-flow-gun-v2.md) plan.
- Do not build a shared surface framework before the package-local experiment
  produces useful evidence.

## Benchmark Behavior And Causal Model

The Python BasicGFSurfer port updates its `surf_stats` only from matched
`on_hit_by_bullet` events. It then compares predicted left and right positions
against those hit-derived statistics. A miss does not update its danger array.

Consequently, these quantities must remain distinct:

```text
hit danger:
  where our real bullets hit this target
  primary proxy for the danger learned by BasicGFSurfer

shot exposure:
  where our confirmed real bullets actually travelled
  useful diagnostic and possible later input for other surfer families

target occupancy:
  where the target was when our real or evaluation wave resolved
  behavior evidence, not danger
```

The main hypothesis becomes:

```text
after enough real hits establish a danger surface,
does this target's later movement avoid historically dangerous GF regions
more strongly than non-surfer controls do?
```

The experiment must use lagged evidence. A shot or hit must not contribute to
the danger surface used to judge its own visit. Otherwise successful targeting
would create a mechanical positive correlation and obscure whether later
movement changed.

## Surface Model

Maintain three per-target, battle-lifetime profiles over the configured
guess-factor bins:

```text
hit_danger_surface[bin] =
  smoothed real-hit GF density

shot_exposure_surface[bin] =
  smoothed confirmed real-shot GF density

target_occupancy_surface[bin] =
  smoothed resolved wave-visit GF density
```

For the BasicGFSurfer benchmark, the initial hit kernel should mirror its
unweighted hit update closely enough to test the causal hypothesis. Keep bullet
power and damage in diagnostics, but do not silently power-weight the base
surface. Any damage-weighted alternative is a later isolated experiment.

All three profiles use the shared asymmetric guess-factor geometry. Actual
bullet direction must be normalized against the associated wave's head-on
bearing, lateral direction, and positive or negative maximum escape angle.

Profiles persist across rounds within a battle, matching the benchmark's danger
memory, and clear at battle boundaries. They remain separated by target.

Interpret the hit-danger surface as:

```text
local minima = candidate low-danger valleys
local maxima = learned-danger ridges
basin width = how broad a candidate region is
valley depth/prominence = how stable the valley is against smoothing noise
```

Target occupancy validates whether the target later visits low-danger regions.
Shot exposure measures what we fired and helps distinguish sparse hit evidence
from narrow firing behavior. Neither surface is relabeled as hit danger.

## Phase 0: Add Generic Real-Shot Lifecycle Evidence

The current component protocol receives resolved `GunVisit` objects but not the
actual `BulletFiredEvent` direction or later bullet outcome. Add narrow shared
gun-system delivery for:

```text
confirmed shot:
  bullet id
  target id
  fire turn
  actual source x/y
  actual bullet direction, power, and speed
  associated GunWave context
  actual normalized shot GF

shot outcome:
  bullet id
  target id
  hit or non-hit result when observable
  hit position, power, and damage for real hits
  associated confirmed-shot and GunWave context
  actual normalized hit GF
```

Requirements:

- Promote the pending wave only after the real bullet-fired event.
- Associate the promoted wave with the real bullet id.
- Derive shot and hit GFs from actual event geometry, not speculative pre-fire
  bearings.
- Dispatch confirmed shots and outcomes generically; do not make
  `VirtualGunSystem` import or special-case `AntiSurferGun`.
- Allow components that do not consume these events to remain simple no-ops or
  non-observers.
- Ensure unfired aims and evaluation waves never update real-shot or hit-danger
  profiles.
- Feed the Anti-Surfer observer with shots and hits from all selected gun modes.

At confirmed fire time, attach an immutable snapshot or equivalent versioned
view of the pre-shot hit-danger profile to the real wave. The later resolved
visit uses that pre-shot view for lagged diagnostics. The current shot and any
eventual hit cannot contaminate their own evidence.

## Phase 1: Passive Falsification With Current Aim Preserved

Record all three surfaces while retaining the current
`occupancy_baseline` aim policy. Add only the telemetry required to test the
hypothesis:

```text
anti_surfer_policy
anti_surfer_hit_count
anti_surfer_shot_count
anti_surfer_occupancy_count
anti_surfer_prior_hit_danger_at_visit
anti_surfer_prior_hit_danger_percentile
anti_surfer_distance_from_recent_hit
anti_surfer_post_hit_shift
anti_surfer_exposure_at_visit
anti_surfer_surfer_relevance
anti_surfer_evidence_mature
```

Package-specific fields belong in component metadata, `visit_diagnostics()`,
or a sampled package-local telemetry event. Avoid expanding generic fire
telemetry with every future valley metric.

Add `tools/anti_surfer_surface_summary.py` to report, by target and repeat:

- sample adequacy for hits, confirmed shots, and resolved visits;
- the distribution of prior hit-danger percentiles at later visits;
- event-aligned movement before and after newly recorded hits;
- distance from recent hit kernels over subsequent resolved waves;
- the same measures for BasicGFSurfer and non-surfer controls;
- missing associations, invalid GFs, and self-contaminated samples.

Use shuffled or circularly rotated profile bins as an offline null comparison.
Do not interpret raw hit-danger/occupancy correlation alone as avoidance.

Treat a repeat as mature only after it contains at least eight real hits and
twenty resolved production visits for the target. If a run does not reach that
bar, report it as inconclusive rather than negative.

Proceed only when both exploratory repeats show a directionally consistent,
lagged avoidance response against BasicGFSurfer and that response is stronger
than against the non-surfer controls. Stop or redesign if the differential is
absent, reverses between repeats, or depends on self-contaminated evidence.

## Phase 2: Add Reachable Hit-Danger-Valley Selection

Only after Phase 1 passes, add a candidate aim policy behind an experiment
setting. Smooth the hit-danger surface and find broad local valleys:

```text
smooth with a small symmetric kernel
find local minima below adjacent basin shoulders
measure width, depth, and prominence
ignore isolated one-bin holes
```

Score valleys with current kinematic plausibility:

```text
candidate_score =
  inverse_smoothed_hit_danger
  * kinematic_reachability
  * transition_likelihood
  * conservative_surfer_relevance
```

The first reachability model must include:

- current lateral direction and confidence;
- speed and reversal cost;
- distance and bullet flight time;
- shared wall-limited positive and negative escape geometry.

Wall-limited escape angles define the GF scale but do not, by themselves, prove
that an interior bin is reachable. Do not implement a wall-only mask.

Until hit evidence is mature, fall back to the existing occupancy baseline.
After maturity, fall back when the danger surface is flat, no valley has useful
prominence, or every candidate is kinematically implausible. Keep fallback
reasons explicit in diagnostics.

Add Phase 2 diagnostics only when the candidate exists:

```text
anti_surfer_selected_gf
anti_surfer_selected_bin
anti_surfer_selection_kind       # hit_danger_valley | occupancy_fallback
anti_surfer_fallback_reason
anti_surfer_reachable_mass
anti_surfer_valley_count
anti_surfer_selected_valley_width
anti_surfer_selected_valley_depth
anti_surfer_selected_valley_prominence
anti_surfer_hit_danger_entropy
```

## Phase 3: Force-Test In Isolation

Add the centralized Adaptive setting:

```text
ROBOCODE_ADAPTIVE_ANTI_SURFER_SURFACE=
  occupancy_baseline | hit_danger_valley
```

Parse it through `adaptive_config.py`, represent it in the Adaptive gun policy,
pass it into `AntiSurferGunConfig`, and include it in the effective
`bot.config` snapshot and fingerprint. Keep numerical defaults in typed config;
do not create an environment variable for every kernel or threshold.

Force `anti_surfer` for both sides and use identical firepower policy. Compare:

1. current `occupancy_baseline`;
2. candidate `hit_danger_valley`;
3. forced production `dynamic_cluster` as a global control.

Required questions:

```text
does reachability reject implausible valleys?
do selected valleys receive later occupancy?
does the candidate improve real conversion after hit evidence matures?
does it add conditional value in wall or reversal contexts?
does it remain useful outside the single surfer benchmark?
```

If the candidate cannot beat the current Anti-Surfer baseline, stop. If it
improves Anti-Surfer but remains globally weaker than Dynamic Cluster, retain it
only as a force-testable situational experiment until distinct conditional
value is repeated.

## Phase 4: Add Coarse Shrinkage Only After A Global Win

Anti-Surfer hit data is sparse. Do not start with exact segments. After the
global hit-danger candidate wins, test one coarse surface at a time:

```text
distance bucket
wall-context bucket
lateral-direction-confidence bucket
surfer-relevance bucket
```

Blend coarse and global surfaces with sample-based shrinkage:

```text
surface = global * (1 - trust) + coarse * trust
trust = f(coarse_hit_count)
```

Require later-window or held-out improvement before retaining a dimension.
Keep real-shot conversion analysis offline; do not add a sparse online
cross-product or depend on a removed shared calibration subsystem.

## Phase 5: Optional Signals, One At A Time

Only after the hit-danger base is validated may these become isolated
experiments:

```text
recency weighting within hit danger
damage-weighted hit danger
confirmed-shot exposure as a soft modifier for other surfer families
normal-gun model density as a soft disagreement feature
```

None may replace real hit danger for the BasicGFSurfer benchmark without new
evidence. Promote one modifier at a time and remove rejected branches rather
than leaving dormant legacy paths.

## Implementation Sequence

1. Add confirmed-shot and shot-outcome models plus generic gun-system delivery.
2. Associate real bullet ids with promoted gun waves and compute actual shot and
   hit GFs using shared asymmetric geometry.
3. Split Anti-Surfer state into hit-danger, shot-exposure, and target-occupancy
   profiles while preserving current aim.
4. Add pre-shot danger snapshots and passive lagged diagnostics.
5. Add `anti_surfer_surface_summary.py` and unit tests for its evidence rules.
6. Run Phase 1 against Python BasicGFSurfer and non-surfer controls.
7. Stop if the mature lagged avoidance differential is not repeatable.
8. Add hit-danger valley analysis and kinematic reachability behind the
   centralized experiment setting.
9. Force-test baseline, candidate, and Dynamic Cluster with matched firepower.
10. Add coarse shrinkage or optional signals only after the simpler candidate
    wins.
11. Revisit selector thresholds or live selectability only in a separate,
    evidence-backed step.

## Unit Verification

Required deterministic tests:

```text
unfired aim does not update exposure or hit danger
evaluation wave does not update real-shot profiles
confirmed real shot from any gun mode updates exposure once
actual fired direction, not intended bearing, determines shot GF
real hit updates hit danger once and retains bullet association
miss does not update hit danger
resolved visit updates occupancy but not exposure or hit danger
lagged visit diagnostic uses the pre-shot danger snapshot
current shot and hit cannot contaminate their own lagged evidence
profiles persist across rounds and clear across battles
flat or immature hit-danger surface uses occupancy fallback
broad reachable valley selects its basin center
one-bin noise hole is ignored
reversal cost and flight time reject an unreachable valley
wall geometry uses shared asymmetric GF scaling
non-observer gun components remain unaffected by lifecycle delivery
configuration setting appears in bot.config and changes its fingerprint
summary tool rejects missing associations and insufficient evidence
```

Run the focused tests and then the full suite:

```sh
PYTHONPATH=bots .venv/bin/python -m pytest tests/test_gun_stats.py
PYTHONPATH=bots .venv/bin/python -m pytest tests/test_adaptive_config.py
PYTHONPATH=bots .venv/bin/python -m pytest tests/test_anti_surfer_surface_summary.py
PYTHONPATH=bots .venv/bin/python -m pytest
```

## Battle Verification

### Passive hypothesis check

Use telemetry with production aiming unchanged:

```sh
scripts/run-battle.sh --telemetry --rounds 16 \
  bots/adaptive-prime bots/ports/basic-gf-surfer-port

tools/telemetry_audit.py <run-dir>/telemetry --require-bot adaptive-prime
tools/anti_surfer_surface_summary.py <run-dir>/telemetry --bot adaptive-prime
```

Repeat once independently. Run at least one non-surfer control, such as
`chase-lock`, with the same diagnostics. If either surfer repeat is immature,
extend evidence rather than weakening the sample gate.

### Forced exploratory A/B

Use the same code on both sides and change only the experiment setting:

```sh
scripts/run-ab.sh \
  --name anti-surfer-hit-danger-exploration \
  --preset adaptive-1v1-basic-gf-surfer-port \
  --baseline . \
  --candidate . \
  --baseline-env ROBOCODE_ADAPTIVE_GUN_MODE=anti_surfer \
  --baseline-env ROBOCODE_ADAPTIVE_ANTI_SURFER_SURFACE=occupancy_baseline \
  --candidate-env ROBOCODE_ADAPTIVE_GUN_MODE=anti_surfer \
  --candidate-env ROBOCODE_ADAPTIVE_ANTI_SURFER_SURFACE=hit_danger_valley \
  --rounds 16 \
  --repeats 2 \
  --telemetry

tools/combat_economics_summary.py battle-results/ab/<experiment>
tools/gun_eval_summary.py <baseline-run>/telemetry --bot adaptive-prime
tools/gun_eval_summary.py <candidate-run>/telemetry --bot adaptive-prime
tools/anti_surfer_surface_summary.py <baseline-run>/telemetry --bot adaptive-prime
tools/anti_surfer_surface_summary.py <candidate-run>/telemetry --bot adaptive-prime
```

`combat_economics_summary.py` is a raw score, firepower, damage, and conversion
summary. Do not apply converted-bot accuracy filtering to the native Python
surfer port.

Also run an eight-round forced smoke against a local bot to catch lifecycle,
fallback, or runtime regressions.

### Promotion confirmation

Only after exploratory evidence is positive:

- run `24 rounds x 3 repeats` against the Python BasicGFSurfer port without
  telemetry for the performance comparison;
- run one separate matched telemetry validation after the performance result;
- compare with forced Dynamic Cluster under the same firepower policy;
- obtain explicit approval before the `50+`-round confirmation suite, as
  required by the tooling workflow.

Judge primarily on raw real-hit rate, damage per fired energy, repeat stability,
post-maturity conversion, fallback rate, valley diagnostics, and clean
telemetry associations. Do not use stuck-surfer filtering, excluded-round
counts, or legacy converted-opponent scores as promotion evidence.

## Promotion Bar

Do not change the default aim policy or selector behavior unless all of the
following hold:

1. Two mature passive repeats show a directionally consistent lagged avoidance
   response against Python BasicGFSurfer.
2. The response is stronger than the same measurement against non-surfer
   controls and survives the offline null comparison.
3. The candidate beats `occupancy_baseline` in the majority of promotion
   repeats and in the aggregate without relying on changed firepower.
4. Reachability and fallback diagnostics are valid, associations are complete,
   and telemetry audit is clean.
5. The candidate has either competitive global performance versus Dynamic
   Cluster or repeated, explainable conditional value that justifies keeping it
   force-testable.

The first acceptable outcome may remain a force-testable situational gun. If
the causal hypothesis fails, remove the new aim branch and retain only generic
lifecycle improvements that have independent value and clean tests.
