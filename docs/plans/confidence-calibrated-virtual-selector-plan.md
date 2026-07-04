# Damage-Calibrated Virtual Selector Plan

This plan describes an upgrade to virtual gun selection:

```text
Damage-Calibrated Virtual Selector
```

This is not a new aim formula. It is a better decision layer for choosing which
gun is allowed to control real shots.

The original version of this plan targeted calibrated real hit probability. That
is still a useful alternative and should remain visible in telemetry. The
current combat-economics direction makes expected shot value the primary target:

```text
estimated gun value =
  calibrated_real_hit_probability
  * proposed_bullet_damage
  - uncertainty_penalty
  - enemy_pressure_cost
```

Keep both views during passive and shadow phases:

```text
hit_probability_score
damage_value_score
```

Do not decide upfront which one is final. Let telemetry and port-focused A/Bs
show whether hit probability or damage value predicts better live performance.

## Current Selector

The current selector is mostly a virtual-score selector with gates.

It does:

```text
1. score each available gun from virtual wave visits
2. optionally blend global and segment scores
3. subtract low-visit confidence penalty if enabled
4. subtract traditional_gf source penalty if configured
5. require min visits
6. require min score
7. require switch margin over current gun
8. switch to best candidate
```

Current score shape:

```text
score = 0.7 * rolling_virtual_score + 0.3 * virtual_accuracy
```

This answers:

```text
which gun has the best virtual score after gates?
```

The calibrated selector should answer:

```text
given this gun's virtual score, source, samples, context, proposed firepower,
and past real conversion, what real shot value should we expect if selected now?
```

Alternative shadow question:

```text
what is the probability this gun will actually hit if selected now?
```

## Validated Implementation Direction

Keep the current selector available as the default selector.

The repository already has a narrow selector boundary:

```text
VirtualGunSystem -> AimModeSelector -> GunSwitchCandidate diagnostics
```

The calibrated implementation should therefore be a second selector strategy,
not a replacement of the existing one:

```text
virtual_score selector:
  current AimModeSelector behavior

damage_calibrated selector:
  same availability, visit, score-floor, forced-mode, and margin semantics
  but candidate decision score can use online calibration
```

`VirtualGunSystem` should instantiate the selector from runtime config. Shared
defaults must continue to use the current selector. Adaptive Prime should be the
first bot wired to the calibrated selector, behind an explicit disabled-by-
default config/env flag during passive and shadow phases.

Do not implement live calibrated selection before the combat-economics
foundation exists:

1. Shared `CombatRegime` vocabulary.
2. `CombatProfileStore` or equivalent real combat profile.
3. Fire-time shot-value telemetry from the EV fire-gate work.
4. Real shot outcome attribution by gun/source/regime/firepower.

Without those inputs, selector calibration can improve hit rate while still
choosing low-value shots that lose bullet damage.

Forced gun mode must bypass calibrated selection. It may still record passive
calibration observations, but it must not be blocked, reranked, or exploration-
modified by calibration.

The current `GunDecisionContext`, per-mode policies, `AimSolution`, and
`GunSwitchCandidate` diagnostics already provide most of the source/context
surface needed for calibration. Avoid adding concrete-gun branches to selector
logic; source-specific behavior should come from generic decision context and
policy/config data.

## Target Behavior

The selector should prefer calibrated expected shot value over raw virtual
score when damage-value evidence is reliable. Calibrated real hit probability
remains a shadow score and possible fallback when damage-value evidence is too
sparse.

Example:

```text
traditional_gf raw virtual score: 0.32
dynamic_cluster raw virtual score: 0.27
```

Current selector may choose `traditional_gf`.

Calibrated selector may choose `dynamic_cluster`:

```text
traditional_gf global source:
  virtual score = 0.32
  post-switch real hit rate = 0.09
  hit_probability_score = 0.17
  damage_value_score = 0.15

dynamic_cluster:
  virtual score = 0.27
  post-switch real hit rate = 0.20
  hit_probability_score = 0.25
  damage_value_score = 0.31 if proposed firepower is stronger
```

The goal is not to punish one gun forever. The goal is to learn when each score
source is trustworthy and valuable.

## Calibration Inputs

Track calibration by:

```text
target id
gun mode
profile/source type
combat regime subset
distance bucket
wall bucket
sample bucket
target speed/lateral bucket
raw virtual score bucket
proposed firepower bucket
enemy pressure bucket
```

Source type examples:

```text
traditional_gf_global
traditional_gf_blend
traditional_gf_coarse_blend
traditional_gf_coarse
traditional_gf_segment
dynamic_cluster
linear
anti_surfer
displacement
calibrated_hybrid
```

Calibration record should store:

```text
opportunities
real_shots
real_hits
post_switch_shots
post_switch_hits
virtual_score_sum
real_hit_rate
damage_per_shot
avg_hit_power
expected_bullet_damage
calibration_error
last_updated_turn
```

## Real Conversion Tracking

Virtual wave score is useful, but it is not enough.

Track real conversion after selection:

```text
when a real bullet is fired:
  record selected gun mode
  record selected source/context
  record raw score and adjusted score

when bullet resolves:
  hit or miss updates real conversion for that source/context
```

Use existing fired-bullet tracking where possible. The important link is:

```text
bullet_id -> selected gun mode/source/context at fire time -> hit/miss result
```

The fire-time snapshot must be stored when the real bullet is confirmed by
`BulletFiredEvent`, because later selector state may have changed. The snapshot
should include:

```text
bullet_id
target id
selected mode
selected source/context
segment/context key
raw score
adjusted selector score
calibrated score if shadow/live is enabled
confidence/source/calibration penalties
fire turn
```

Use the bot API outcome callbacks for real conversion:

```text
on_bullet_hit -> hit
on_bullet_hit_wall -> miss
on_bullet_hit_bullet -> miss or blocked-miss bucket
round end / target death before resolution -> unresolved, ignored
```

The existing `FiredBulletTracker` is useful for telemetry attribution, but the
online selector should own or receive a calibration-specific outstanding-shot
record so live decisions do not depend on debug telemetry storage.

Also track post-switch windows:

```text
after selector switches to mode X:
  next N real shots by X update post-switch conversion
```

This specifically catches guns that switch well on paper but fail after taking
control.

`tools/gun_eval_summary.py` already reports an offline `calibration` table using
`gun.switch_decision`, `bullet.fired`, and `bullet.hit_bot`. The online selector
calibration should reuse that terminology carefully: offline summary remains an
analysis tool, while the new calibration store is live battle state used for
passive measurement, shadow scoring, and later gated selection.

## Calibrated Scores

Primary formula:

```text
damage_value_score =
  calibrated_hit_probability
  * bullet_damage_for_power(proposed_firepower)
  - uncertainty_penalty
  - source_penalty
  - enemy_pressure_cost
```

Alternative shadow/fallback formula:

```text
hit_probability_score =
  raw_virtual_score
  * reliability_multiplier
  - uncertainty_penalty
  - source_penalty
```

Where:

```text
reliability_multiplier =
  blend(global_mode_reliability, context_reliability, context_weight)
```

Simple version:

```text
expected_real_hit_rate = smoothed_real_hits / smoothed_real_shots
expected_from_virtual = raw_virtual_score
calibration_error = expected_from_virtual - expected_real_hit_rate

hit_probability_score = raw_virtual_score - calibration_error_weight * max(0, calibration_error)
```

Use Bayesian smoothing so low sample counts do not overreact:

```text
smoothed_hit_rate =
  (hits + prior_hits) / (shots + prior_shots)
```

Initial prior:

```text
prior_shots = 12
prior_hit_rate = mode baseline or global bot baseline
```

Damage-value calibration should use the same calibrated hit probability, but
multiply it by the proposed bullet damage. Enemy pressure cost should come from
the combat profile, not from gun-specific hacks. If combat profile data is
missing, set enemy pressure cost to zero and keep the damage score marked as
low-confidence.

## Context Confidence

Not all calibration buckets should be trusted equally.

Confidence:

```text
context_confidence = clamp(real_shots / full_weight_shots, 0, 1)
```

Then:

```text
hit_probability_score =
  raw_score * (1 - context_confidence)
  + context_adjusted_score * context_confidence
```

This keeps early behavior close to current selector and lets calibration take
over as evidence accumulates.

Damage-value selection should require separate confidence:

```text
damage_value_confidence =
  min(context_confidence, combat_profile_confidence, firepower_bucket_confidence)
```

If `damage_value_confidence` is low, live selection should fall back to the
current virtual selector or the calibrated hit-probability score depending on
which shadow mode performed better.

## Source-Specific Rules

Start with explicit rules only where evidence already points to risk.

Traditional GF:

```text
global source:
  high skepticism

blend / coarse_blend:
  skepticism proportional to low blend weight

coarse / segment:
  normal trust if real conversion is acceptable
```

Anti-surfer:

```text
require stronger real conversion before live selection
because valley shots are high variance
```

Dynamic cluster:

```text
allow normal trust
but downweight sparse-neighbor contexts later
```

Linear:

```text
trust early
downweight after enough evidence shows enemy is non-linear
```

## Exploration

Calibration needs data. Add bounded exploration for promising candidates.

Rules:

```text
never explore when energy is critically low
never explore with very low firepower confidence
never explore more than one shot per interval
only explore candidates close to current best
```

Example:

```text
if candidate raw score is within 0.05 of best
and calibration samples are low
and gun heat is ready
then allow one exploration shot
```

This should be disabled by default until the base calibration works.

## Code Structure

Suggested modules:

```text
bots/bot_core/gun/calibration.py
  GunCalibrationKey
  GunCalibrationStats
  GunCalibrationStore
  GunSelectionSnapshot
  hit_probability_score()
  damage_value_score()

bots/bot_core/gun/aim.py
  AimModeSelector remains the current virtual-score selector
  DamageCalibratedAimModeSelector applies calibration when enabled
  shared selector protocol/helper preserves forced-mode and gate semantics

bots/bot_core/gun/models.py
  config fields
  diagnostics fields

bots/bot_core/telemetry/fire.py
  selector calibration telemetry
```

Potential config fields:

```text
selector_strategy: str = "virtual_score"
selector_calibration_enabled: bool = False
selector_calibration_shadow: bool = False
selector_calibration_prior_shots: int = 12
selector_calibration_prior_hit_rate: float = 0.14
selector_calibration_full_weight_shots: int = 40
selector_calibration_error_weight: float = 0.6
selector_damage_value_enabled: bool = False
selector_damage_value_shadow: bool = False
selector_damage_value_min_confidence: float = 0.45
selector_enemy_pressure_cost_scale: float = 1.0
selector_exploration_enabled: bool = False
selector_exploration_interval: int = 24
selector_exploration_max_score_gap: float = 0.05
```

Adaptive Prime wiring should map bot-specific env/config onto these shared
fields, for example:

```text
ROBOCODE_ADAPTIVE_SELECTOR_CALIBRATION=0|shadow|live
```

All other bots should keep `selector_strategy="virtual_score"` until Adaptive
validation justifies broader rollout.

## Telemetry

Extend `gun.switch_decision` with:

```text
hit_probability_score
damage_value_score
raw_score
proposed_firepower
expected_bullet_damage
calibration_hit_rate
calibration_damage_per_shot
calibration_samples
calibration_error
calibration_confidence
damage_value_confidence
enemy_pressure_cost
calibration_key
exploration_candidate
exploration_selected
```

Add optional event:

```text
gun.selector_calibration
```

Fields:

```text
target
mode
source
context
raw_score
hit_probability_score
damage_value_score
real_shots
real_hits
real_hit_rate
damage_per_shot
avg_hit_power
proposed_firepower
expected_bullet_damage
post_switch_shots
post_switch_hits
post_switch_hit_rate
calibration_error
confidence
```

Telemetry questions:

```text
Which modes are over-confident?
Which modes produce real damage value, not only hit rate?
Which profile sources convert?
Does hit_probability_score predict real hit rate better than raw_score?
Does damage_value_score predict score/bullet-damage outcomes better than hit_probability_score?
Which switch decisions changed because of calibration?
```

## Implementation Phases

Phase 1: passive measurement

```text
record fire-time selector context by bullet id
update real hit/miss conversion from bullet-hit, bullet-wall, and bullet-bullet outcomes
emit calibration telemetry
do not change selection
```

Phase 2: diagnostics summary

```text
extend tools/gun_eval_summary.py
report raw score vs real conversion by mode/source/context
identify over-confident guns
```

Phase 3: shadow calibrated scores

```text
compute hit_probability_score and damage_value_score
log what selector would have chosen
do not change live selection
```

Phase 4: gated selection by chosen score

```text
enable the better shadow score for Adaptive only
keep forced mode unaffected
keep exploration disabled
run A/B
```

Phase 5: bounded exploration

```text
optional
only after calibrated score improves or stays neutral
```

## Validation

Unit tests:

```text
calibration store updates hit/miss by bullet id
Bayesian smoothing avoids overreacting to one hit/miss
context confidence blends raw and calibrated scores
damage-value score includes proposed firepower and bullet damage
damage-value score falls back or stays shadow when confidence is low
selector can choose lower raw score when selected calibrated score is better
forced mode bypasses calibration gates
```

Smoke:

```text
PYTHONPATH=bots .venv/bin/python -m pytest tests/test_gun_stats.py
```

Telemetry run:

```text
scripts/run-battle.sh --rounds 1 bots/adaptive-prime bots/chase-lock
tools/telemetry_audit.py battle-results/runs/<run>/telemetry --require-bot adaptive-prime
```

A/B:

```text
scripts/run-ab.sh --name adaptive-selector-calibration \
  --preset adaptive-1v1-basic-gf-surfer-port \
  --rounds 24 \
  --repeats 3 \
  --telemetry

tools/combat_economics_summary.py battle-results/ab/<experiment>
for telemetry in battle-results/ab/<experiment>/candidate/adaptive-vs-basic-gf-surfer-port/run-*/telemetry; do
  tools/gun_eval_summary.py "$telemetry" --bot adaptive-prime
done
```

Use local bots as smoke/regression checks after the port-focused gate, not as
the primary evidence for the combat-economics problem.

## Promotion Gates

Passive measurement is successful if:

```text
calibration telemetry is complete
bullet outcomes link to fire-time selector context
summary can identify over-confident modes
```

Shadow mode is successful if:

```text
hit_probability_score predicts real hit rate better than raw_score
damage_value_score predicts score/bullet-damage shape better than hit_probability_score
changed decisions look reasonable in telemetry
```

Live calibrated selection is successful if:

```text
overall score improves or stays neutral
bullet damage and damage per shot improve or stay neutral
post-switch hit rate improves
post-switch damage value improves
bad traditional_gf/anti_surfer switches decrease
dynamic_cluster is not unfairly suppressed
```

## Risks

Risk:

```text
calibration can learn too slowly
```

Mitigation:

```text
use smoothed priors and keep current selector behavior until samples accumulate
```

Risk:

```text
calibration can overfit one opponent
```

Mitigation:

```text
store target-specific and global fallback stats separately
validate on multiple benchmarks
```

Risk:

```text
selector becomes too conservative
```

Mitigation:

```text
allow bounded exploration only after base calibration is stable
```

## Bottom Line

Current selector:

```text
virtual score + gates
```

Calibrated selector alternatives:

```text
virtual score -> estimated real hit probability -> switch decision
virtual score -> estimated real shot value -> switch decision
```

This should be a high-value reliability upgrade only if telemetry proves the
chosen calibrated score predicts real outcomes. Keep hit probability and damage
value side by side until the evidence decides which is better for live
selection.
