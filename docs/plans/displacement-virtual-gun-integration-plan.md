# Displacement Virtual-Gun Integration Plan

This plan promotes the improved `displacement` gun from force-testable only to a
normal virtual-gun candidate for all bots.

The gun should enter the live selector as a situational gun, not as the primary
gun. Dynamic Cluster remains the primary KNN-GF learner until live telemetry
proves displacement can replace it more broadly.

## Goals

1. Add `displacement` to the live virtual-gun candidate set for Adaptive Prime,
   Chase Lock, Circle Strafer, and Sweep Pressure.
2. Keep the public mode name `displacement`.
3. Keep Markov-assisted replay ranking enabled by default.
4. Preserve forced-gun testing for `displacement`.
5. Use conservative situational switch gates so displacement can win when KNN is
   weak, without stealing most mature KNN shots.
6. Make selector diagnostics and gun evaluation enough to decide whether later
   confidence gates are needed.

## Non-Goals

- Do not make displacement the primary gun in the first live integration.
- Do not add a hard displacement confidence gate in this step.
- Do not tune selector thresholds from raw BasicGFSurfer scores alone; use
  filtered rounds from `surfer_glitch_analysis.py`.
- Do not introduce a new public gun mode for Markov or replay-density variants.
- Do not use eval-wave scores as a performance gate. They are diagnostics only.

## Current State

`DisplacementGun` is already built by `standard_runtime_config()` with the
shared target-history store:

```text
HeadOnGun
LinearGun
LinearGun(linear_wall_aware)
DisplacementGun
TraditionalGfGun
AntiSurferGun
DynamicClusterGun
```

The blocker is policy, not component registration:

- `DEFAULT_LIVE_GUN_MODES` contains only `linear`, `traditional_gf`, and
  `dynamic_cluster`.
- `GunSelectorConfig.selectable_modes` and `GunScoringConfig.selectable_modes`
  have the same three-mode fallback defaults.
- Adaptive already passes `DisplacementGunConfig` with Markov enabled and strict
  live thresholds, but displacement is not in its selectable set.
- Chase, Circle, and Sweep can force `displacement`, but they do not pass
  displacement-specific live thresholds or Markov env wiring.

The selector already understands mode roles:

- `dynamic_cluster` is primary.
- `linear` is fallback.
- `traditional_gf` and `displacement` are situational.
- Situational guns need a larger margin over primary KNN unless the primary has
  enough low-score visits and the candidate has context evidence.

That means the first integration can rely on existing selector structure.

## Implementation

### 1. Add Shared Displacement Policy

Update `bots/bot_core/gun/policy.py`:

```text
DEFAULT_LIVE_GUN_MODES =
  {"linear", "traditional_gf", "dynamic_cluster", "displacement"}
```

Add shared defaults:

```text
displacement_min_switch_visits = 60
displacement_min_switch_score = 0.08
displacement_markov_enabled = true
```

Add a policy adapter:

```text
displacement_config_from_policy(policy) -> DisplacementGunConfig
```

The adapter should read:

```text
policy.displacement_min_switch_visits
policy.displacement_min_switch_score
policy.displacement_markov_enabled
```

and fall back to the shared defaults when a bot policy does not define them.

### 2. Update Runtime Defaults

Update fallback defaults in `bots/bot_core/gun/config.py`:

```text
GunSelectorConfig.selectable_modes
GunScoringConfig.selectable_modes
```

Both should include `displacement` so ad-hoc runtime configs do not silently
exclude it.

### 3. Wire All Bots

Adaptive Prime:

- Keep explicit `DisplacementGunConfig` wiring.
- Replace strict initial thresholds with the shared live thresholds unless a
  local run shows excessive displacement selection.
- Keep `ROBOCODE_ADAPTIVE_DISPLACEMENT_MARKOV` default-on.

Chase Lock, Circle Strafer, Sweep Pressure:

- Add policy fields:

```text
displacement_min_switch_visits
displacement_min_switch_score
displacement_markov_enabled
```

- Add env flag helpers only for Markov unless threshold sweeps need env control.
- Pass `displacement=displacement_config_from_policy(GUN_POLICY)` into
  `standard_runtime_config()`.

Suggested env flags:

```text
ROBOCODE_CHASE_DISPLACEMENT_MARKOV
ROBOCODE_CIRCLE_DISPLACEMENT_MARKOV
ROBOCODE_SWEEP_DISPLACEMENT_MARKOV
```

### 4. Keep Selector Behavior Conservative

Do not add displacement-specific selector branches.

Use existing generic selector behavior:

- displacement stays `role="situational"`.
- displacement keeps `strengths={"stable_pattern"}` initially.
- Dynamic Cluster keeps the primary role bonus and lower primary-over-fallback
  margin.
- `situational_over_primary_margin` continues protecting mature KNN.
- primary-slump relaxation can allow displacement when KNN has enough visits,
  low score, and displacement has context tags.

Only add a decision penalty later if live telemetry shows bad displacement
switches that are predictable from diagnostics.

Candidate later penalty inputs:

```text
displacement_replay_count
displacement_candidate_score
displacement_peak_share
displacement_bearing_spread
```

Do not gate on `displacement_markov_confidence` yet. The filtered Markov-on vs
density-only BasicGFSurfer runs did not show a clean confidence cutoff.

### 5. Update Tests

Update `tests/test_bot_configs.py`:

- Expected default selectable modes include `displacement` for all four bots.
- Forced `displacement` still works.
- Markov env flags parse for all bots.
- Bot policy adapters pass displacement thresholds and Markov toggle into
  runtime config where practical.

Add or update selector tests in `tests/test_gun_stats.py` if needed:

- displacement is considered when it is in `selectable_modes`.
- displacement remains blocked by situational-over-primary margin when KNN is
  mature and healthy.
- displacement can win when primary KNN is slumping and displacement has context
  evidence.

### 6. Update Docs And Memory

Update:

- `docs/bot-shared-systems.md`: displacement is a live situational candidate.
- `bots/adaptive-prime/README.md`
- `bots/chase-lock/README.md`
- `bots/circle-strafer/README.md`
- `bots/sweep-pressure/README.md`
- `.serena/memories/project/bot-architecture.md`

Keep exact math and displacement internals in
`docs/bot-core-data-structures.md` and the displacement gun README. The
integration docs should describe policy behavior, not duplicate formulas.

## Validation

Run unit and doc checks:

```sh
PYTHONPATH=bots .venv/bin/python -m pytest
git diff --check
```

Run short live-gun smoke battles:

```sh
scripts/run-battle.sh --telemetry --rounds 12 bots/adaptive-prime bots/chase-lock
scripts/run-battle.sh --telemetry --rounds 12 bots/adaptive-prime bots/circle-strafer
scripts/run-battle.sh --telemetry --rounds 12 bots/adaptive-prime bots/sweep-pressure
```

Run a BasicGFSurfer live-gun check:

```sh
scripts/run-battle.sh --telemetry --rounds 24 bots/adaptive-prime --legacy basic-gf-surfer
tools/surfer_glitch_analysis.py battle-results/runs/<run>
tools/gun_eval_summary.py battle-results/runs/<run>/telemetry --bot adaptive-prime
tools/telemetry_audit.py battle-results/runs/<run>/telemetry --require-bot adaptive-prime
```

Expected live behavior:

- `displacement` appears in `virtual_scores` and `gun.wave_visit`.
- `displacement` is selected sometimes, not constantly.
- Dynamic Cluster remains the dominant selected gun after it matures unless its
  score is poor.
- Surfer filtered rounds do not show a score or first-place collapse.
- Telemetry audit reports no issues.

## Tuning Rules

If displacement is never selected:

1. Inspect `gun.switch_decision` reasons.
2. If mostly `visits`, lower `displacement_min_switch_visits` toward `45`.
3. If mostly `score_floor`, lower `displacement_min_switch_score` toward `0.06`.
4. If mostly `margin`, inspect whether KNN is actually healthy before changing
   `situational_over_primary_margin`.

If displacement is selected too often:

1. Check whether selected displacement shots have poor post-switch real hit
   conversion.
2. Raise `displacement_min_switch_visits` toward `90`.
3. Raise `displacement_min_switch_score` toward `0.12`.
4. Prefer a diagnostics-based decision penalty over broad selector margin
   changes if bad switches correlate with weak replay quality.

If surfer raw score improves but filtered score regresses:

1. Treat raw improvement as suspect.
2. Compare filtered score, firsts, displacement real hit rate, and displacement
   wave average.
3. Keep KNN primary and either raise displacement gates or add diagnostics
   penalty.

## Acceptance Criteria

The first integration is acceptable when:

- All four bots include `displacement` in live selectable modes.
- Forced `displacement` still works for all four bots.
- Markov can be disabled per bot for testing.
- Unit tests and `git diff --check` pass.
- At least one live telemetry run shows displacement scoring and selector
  decisions.
- BasicGFSurfer analysis is based on filtered rounds.
- No hard confidence gate is added without telemetry evidence.
