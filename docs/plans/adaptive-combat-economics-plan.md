# Core Combat Economics Plan

Status: executed through the first Phase 5 behavior gate in July 2026 after the
Traditional GF, KNN, selector, and PIF cleanup work. The telemetry foundations
remain; the tested live movement and fire candidates were rejected.

The original combat-economics direction remains useful, but its July 4 battle
evidence is historical. The current gun stack and Python Basic GF Surfer port
are materially different. The current `main` baseline and variance were
remeasured before the behavior experiments recorded below.

## Decision

Proceed in this order:

1. Establish a fresh current-main baseline.
2. Build a time-aligned combat ledger without changing behavior.
3. Split movement occupancy, real-hit danger, and expected-wave pressure.
4. Test real-hit danger as an isolated movement change.
5. Calibrate fire utility in shadow mode.
6. Test fire/hold and power choice separately.

Do not introduce one universal hard-bucket `CombatRegime`. Use canonical
continuous context and small subsystem-specific adapters. Do not restore the
PIF replay bonuses removed during false-optimization cleanup. Selector
calibration and anti-surfer reconstruction remain separate follow-up plans.

## Problem To Revalidate

The historical symptom was poor damage exchange despite acceptable score or
first-place results:

- too much enemy bullet damage received;
- too little damage returned per accepted shot and per unit of fired energy;
- fire decisions that treated hit probability as the full value of a shot;
- movement learning that mixed ordinary visits, inferred pressure, and real
  bullet hits into one danger signal.

Recent gun and selector corrections may have changed the size or even the
existence of that problem. The Python
`bots/ports/basic-gf-surfer-port` implementation is the primary focused
opponent. Converted legacy bots may provide diagnostics, but they are not a
promotion gate.

If the fresh baseline does not reproduce a meaningful combat-economics problem,
stop and rewrite the remaining hypotheses from the new evidence.

## Goals

- Measure the exchange between accepted shots, fired energy, damage dealt, and
  damage received.
- Give movement real-hit evidence semantics distinct from ordinary occupancy
  and transient inferred pressure.
- Estimate fire utility from observable outcomes before changing fire behavior.
- Improve focused surfer performance without hiding a serious regression
  against ordinary local opponents.
- Keep every experiment attributable to one behavior change.

## Non-Goals

- No opponent-name special cases.
- No universal high-cardinality combat-regime key.
- No new PIF replay-candidate bonuses or discrete coarse replay rewards.
- No dynamic firepower floors.
- No simultaneous selector recalibration.
- No anti-surfer gun rebuild inside this plan.
- No compatibility switches or dead experiment branches after a decision.

## Design Rules

### Count accepted shots, not requested shots

An own shot exists only after the engine accepts it and returns a fired bullet.
Use the existing pending-gun-wave and fired-bullet attribution path. Requested
fire commands must not enter conversion or energy accounting as real shots.

### Keep evidence meanings separate

These observations are not interchangeable:

- **visit occupancy:** where the enemy or our bot passed while a wave existed;
- **real hit danger:** where an actual bullet hit;
- **expected pressure:** unresolved or low-confidence inferred enemy fire.

Expected pressure may affect a current decision, but it must not become a
permanent real-hit observation when no hit occurred.

### Instrument before acting

Each new metric first runs in telemetry or shadow mode. A behavior phase starts
only when attribution coverage, sample volume, and calibration are adequate.

### Change one decision dimension at a time

Fire/hold at the current selected power is one experiment. Choosing a different
power is another. Gun selection is a third and remains outside this plan.

### Validate Adaptive Prime before sharing behavior

Shared data structures may live in `bot_core`, but new live policy remains
disabled for other bots until Adaptive Prime has focused evidence and release
smokes.

## Phase 0: Fresh Current-Main Baseline

### Purpose

Replace the stale July 4 baseline and quantify current variance before setting
promotion thresholds.

### Configuration

- Use the normal Adaptive Prime selector and current production configuration.
- Use the Python Basic GF Surfer port as the primary target.
- Do not force an individual gun for the main economics baseline.
- Keep performance runs telemetry-free.

### Diagnostic run

Start with one 12-round telemetry run:

```sh
scripts/run-battle.sh \
  --rounds 12 \
  --telemetry \
  bots/adaptive-prime \
  bots/ports/basic-gf-surfer-port
```

Then inspect the generated run with:

```sh
tools/telemetry_audit.py \
  battle-results/runs/<run>/telemetry \
  --require-bot adaptive-prime

tools/combat_economics_summary.py battle-results/runs/<run>

tools/gun_eval_summary.py \
  battle-results/runs/<run>/telemetry \
  --bot adaptive-prime
```

A second 12-round run is allowed when the first run reveals a clear telemetry
gap or unusually noisy result. Do not tune behavior from one run.

### Variance and promotion baseline

After diagnostics are trustworthy, use a current-tree series to estimate
variance. A `3 x 24` series is the preferred promotion baseline, but it exceeds
50 total rounds and therefore requires explicit user approval:

```sh
scripts/run-battle-series.sh \
  --runs 3 \
  --rounds 24 \
  bots/adaptive-prime \
  bots/ports/basic-gf-surfer-port
```

Record at minimum:

- score share and first places;
- our bullet damage and enemy bullet damage;
- accepted shots and inferred enemy shots;
- average accepted firepower and average hit power;
- damage per accepted shot;
- damage per unit of fired energy when supported by the summary tool;
- shots and hits by selected gun/source;
- inferred enemy-fire coverage;
- real enemy-hit-to-wave match coverage.

### Exit gate

Phase 0 is complete only when:

- the current problem is stated from current evidence;
- telemetry attribution gaps are known;
- baseline variance is measured well enough to define numeric regression gates;
- later phases are either confirmed as relevant or explicitly removed.

### Current evidence

The 2026-07-15 current-main diagnostic (`20260715-194007`) reproduced the
historical problem over 12 rounds: Adaptive won `8/12` first places through
survival but lost score `803-909` and bullet damage `281-607`. It accepted `721`
shots at `13.2%` accuracy; Dynamic Cluster supplied `615` low-power shots at
`0.68` average power. The focused combat-economics problem therefore remains
relevant.

The telemetry-only combat ledger was then implemented and validated against
Tank Royale's terminal callback ordering. The final 12-round Phase 1 run
(`20260715-200823`) reconciled `721` accepted bullets to `721` final outcomes,
including `106` hits and `320.9` damage. It recorded `659` inferred enemy shots
and `74` real enemy hits, with `95.9%` movement-wave match coverage. Seven
winning-hit callbacks corrected provisional round-end misses; the audit
reported no issues.

The runner can terminate a defeated bot before `on_death` or all per-bullet
round-close telemetry is emitted. Run summaries therefore reconcile accepted
`bullet.fired` records and real hit callbacks at terminal EOF, treating bullets
still in flight as misses. This is analysis-only and does not alter bot
behavior. The final review also covered the inverse terminal ordering: target
death precedes the accepted-fire callback, so target cleanup now retains the
pending gun wave until that callback and the ledger counts even a genuinely
unattributed accepted bullet.

The approved telemetry-free `3 x 24` variance series
(`20260715-220305`) completed on the current tree. Across 72 rounds Adaptive
scored `5056` to the surfer's `5491`, won `50/72` first places, dealt `1799`
bullet damage, and received `3837`. Repeat-level Adaptive score share averaged
`48.1%` with `6.2` percentage-point sample deviation (`41.2%` to `53.0%`);
first-place rate averaged `69.4%` with `9.6` percentage-point deviation
(`58.3%` to `75.0%`). Adaptive score per round averaged `70.22 +/- 6.70`, own
bullet damage per round `24.99 +/- 0.77`, and enemy bullet damage per round
`53.29 +/- 5.48`.

Predeclare the focused A/B regression floor as `42%` aggregate score share and
`60%` first-place rate, approximately one observed repeat-level standard
deviation below the current means. For the movement experiment, also require
own bullet damage per round of at least `24.2`, while enemy bullet damage must
improve in at least two of three repeats and in aggregate. The separate live
telemetry attribution run must confirm that any defensive gain is not explained
by materially fewer accepted shots or lost firing opportunities.

## Phase 1: Shared Combat Ledger, Telemetry Only

### Purpose

Create one observable, time-aligned account of combat events without changing
movement, fire, or selection behavior.

### Proposed ownership

Add a small shared module such as:

```text
bots/bot_core/combat/profile.py
```

Possible public concepts:

```text
CombatProfileStore
CombatProfileSnapshot
```

Names are provisional. Prefer the smallest interface that fits existing bot
event plumbing.

### Events

Track:

- accepted own bullet fires, including power, gun mode, source, and context;
- resolved own bullet hits and misses;
- inferred enemy fires with inference confidence;
- real enemy bullet hits and their matched wave when available.

Maintain both lifetime totals and a recent **turn window**. Do not compute a
damage delta by subtracting unrelated fixed-length event deques: sparse hit and
fire streams cover different time spans. All recent values must share the same
turn bounds.

### Derived observations

Expose objective quantities and conservative observable tags such as:

```text
damage_deficit
low_our_conversion
high_enemy_damage
enemy_fire_detection_weak
```

Do not emit behavior labels such as `surfer_like`, do not duplicate the current
FireGate `last_stand` logic, and do not depend on a runtime score field that has
not been proven available.

### Telemetry

Emit a versioned `combat.profile` event or equivalent fields containing:

- recent and lifetime window bounds;
- accepted shots, resolved outcomes, and fired energy;
- damage dealt and received;
- enemy-fire confidence totals;
- attribution coverage and observable tags.

### Exit gate

- Unit tests cover accepted-shot semantics, turn-window expiry, delayed
  outcomes, and confidence weighting.
- A 12-round telemetry run passes audit.
- Summary totals reconcile with existing bullet and gun telemetry within an
  explained tolerance.
- No live decision consumes the ledger yet.

## Phase 2: Split Movement Evidence, Shadow First

### Current defect

The current flattener can record ordinary wave visits and weighted real bullet
hits into the same movement profile. Expected waves may also mature into
ordinary visits. That makes a dense travel lane look like proven bullet danger
and lets uncertain inference persist as fact.

### Target evidence stores

Separate at least:

```text
visit_occupancy_profile   # ordinary wave passage
enemy_hit_profile        # matched real enemy bullet hits
expected_wave_pressure   # transient, confidence weighted, not permanent truth
```

Reuse `MovementProfile` and `MovementStatsBufferSet` where their mechanics fit;
do not duplicate kernels or bin math. The semantic separation matters more than
new container types.

### Context policy

Do not key all three stores by one giant regime. Begin with the movement inputs
already known to influence escape and risk, for example distance, bullet power,
lateral motion, and wall state. Prefer continuous similarity or a small
hierarchical adapter. Add a dimension only after telemetry shows that it
improves prediction without destroying sample density.

Current validated gun models keep their own feature shapes. In particular, this
phase must not add bonuses to PIF replay candidate ranking.

### Shadow telemetry

For each movement choice, report the candidate's:

- wall and position risk;
- occupancy density;
- real-hit danger;
- transient expected pressure;
- hit-profile support and fallback level;
- selected direction under current behavior and under the shadow formula.

Also report wave-match error and the fraction of real hits that could update the
hit profile.

### Current evidence

The shadow-only implementation keeps the existing composite movement profile
as an explicitly named compatibility input to the live score. In parallel it
records confirmed-wave occupancy, matched real-hit evidence, and active
confidence-weighted expected-wave pressure. Neither the clean evidence stores
nor the shadow choice feed a live command.

The one-round telemetry smoke (`20260715-201814`) recorded `39` confirmed
occupancy passages and `4` expired expected waves with zero permanent occupancy
writes. All `8` real hits matched a movement wave; radial match errors ranged
from `16.98` to `38.21`, below the `55` tolerance. Hit support progressed from
occupancy fallback through blended support to the hit-profile level. The
shadow direction differed on `8/28` sampled direction choices, while the shadow
go-to destination differed on `5/31` samples. The telemetry audit was clean,
and no turn was skipped (`4.554 ms` maximum sampled decision time).

### Exit gate

- Existing movement behavior is unchanged.
- Real hits never enter the occupancy-only channel.
- Unresolved expected waves never become permanent hit evidence.
- Support and match coverage are sufficient to justify a live experiment.

## Phase 3: Enemy-Hit Danger Movement Experiment

### Hypothesis

A movement score that treats matched real hits as stronger evidence than
ordinary occupancy will reduce enemy bullet damage without sacrificing too much
position quality or our own firing opportunity.

### Candidate score

Use the existing position and wall terms, then add evidence in this order:

```text
movement_danger =
  current_position_and_wall_danger
  + supported_enemy_hit_danger
  + smaller_visit_occupancy_term
  + transient_expected_pressure
```

Weights are not fixed by this document. Derive initial bounds from the Phase 2
shadow distributions so no new component dominates merely because its numeric
scale differs.

Use hierarchical fallback when the hit profile is sparse. With no supported hit
evidence, behavior should remain close to the current movement policy.

### Experiment discipline

- Use one explicit Adaptive-only experiment flag.
- Compare the current formula with only the evidence weighting changed.
- Do not change gun selection, fire gate, or firepower in the same A/B.
- Remove the flag and rejected code after the decision.

### Current implementation

Phase 2 shadow distributions set the tested candidate's occupancy weight to
`0.65`, real-hit weight to `1.5` with a `2.0` component cap,
expected-pressure weight to `0.35` with a `1.5` component cap, and hit-only
selection support to `6`.

The approved telemetry-free focused A/B
(`20260715-201328-movement-evidence`) rejected this candidate decisively.
Enemy bullet damage worsened in all three repeats (`1316 -> 1430`,
`1453 -> 1515`, and `1243 -> 1654`), for an aggregate `4012 -> 4599`
(`+14.6%`). Adaptive score fell `4970 -> 3976`, first places fell `48 -> 33`,
and candidate score share was `34.5%`, below the predeclared `42%` floor. Own
bullet damage was nearly unchanged (`1847 -> 1832`), so the regression cannot
be explained as a simple offensive-volume trade.

The candidate was not promoted. Its environment flag, live decision parameter,
and score-selection branch were removed. The clean occupancy/hit/expected
profiles, bounded shadow score, and comparison telemetry remain diagnostic;
live direction and go-to selection always use the legacy score.

### Exit gate

Promote only when the focused A/B improves enemy-damage economics in at least
two of three repeats, stays within the numeric score/first regression bound set
in Phase 0, and telemetry attributes the result to movement rather than reduced
shot volume. Run small non-surfer release smokes before enabling shared defaults.

## Phase 4: Shadow Fire Utility

### Purpose

Estimate the value of an accepted shot without changing whether or how the bot
fires.

For proposed power `p`, define:

```text
q    = calibrated probability that the accepted shot hits
D(p) = bullet damage
B(p) = bullet-hit energy bonus
H(p) = gun heat or time until the next firing opportunity
```

Report two primary utility views:

```text
score_utility       = q * D(p)
energy_swing_utility = q * (D(p) + B(p)) - p
```

Report gun heat and opportunity cost separately at first. An enemy-pressure
penalty may be emitted as a diagnostic, but it must not enter the live utility
until its scale is calibrated against observed outcomes.

### Calibration

Emit these candidate diagnostic dimensions:

- gun mode or generic source type;
- range;
- accepted power;
- model maturity or solution-quality band.

Start with the smallest supported calibration model. Add a diagnostic dimension
to calibration only when it improves held-out or later-window calibration.

### Telemetry

At each accepted shot and each fire opportunity, emit:

- `q`, its support, and fallback level;
- selected power and `D(p)`, `B(p)`, and `H(p)`;
- score and energy-swing utility;
- eventual real outcome for accepted shots;
- the reason current behavior fired or held.

### Current implementation

`FireUtilityCalibrator` now runs in shadow mode using only previously resolved,
engine-accepted bullets. It reuses canonical physics and a global `Beta(1, 5)`
posterior as the causal base rate. Dynamic Cluster solutions with quality at
least `0.10` receive a fixed `1.75x` odds adjustment selected from the held-out
evidence below. Range, power, generic maturity, and gun-mode cross-products
remain diagnostic only. Ready-gun turns freeze causal calibration snapshots for
every accepted-power band and emit `fire.utility_opportunity`; later hold
opportunities retain a pending snapshot until the engine's delayed accepted-fire
callback. Accepted bullets, outcomes, and corrections emit the corresponding
utility lifecycle events. Durable real-hit telemetry is emitted before derived
resolution, and corrections are limited to a real hit replacing a provisional
`round_end` miss. No utility result feeds a live decision.

`tools/fire_utility_summary.py` reconciles durable real-hit events and reports
probability reliability across range, power, mode, quality, fallback, and
chronological windows. It also reports supported-shot coverage, expected
calibration error, Brier skill against the fixed `Beta(1,5)` prior, and hit/miss
probability separation. `tools/telemetry_audit.py` verifies formula values,
bands, the Beta base posterior and quality-odds adjustment, future-support leakage, accepted-bullet
attribution, terminal lifecycle, and correction semantics. Unit-level
implementation checks are complete. The revised candidate later passed the
fresh validation gate recorded below. No fire-utility value currently feeds
live behavior because the first Phase 5A consumer was rejected and removed.

### Phase 4 evidence: run `20260715-211503`

The first 12-round validation captured 749 accepted and resolved shots, but did
not pass the gate. The audit found four accepted shots without a staged
ready-gun opportunity. In each case, a ready fire command was followed by one
or more hold opportunities before the engine's delayed accepted-fire callback;
the hold path had discarded the pending snapshot. One final-round real hit was
also absent from generic durable hit telemetry because derived resolution was
emitted first and the defeated process terminated between the two records.
Both lifecycle defects now have regression tests and fixes.

The old sparse mode/range/power/quality hierarchy produced Brier skill
`-0.0060` against the fixed prior and hit/miss probability separation `+0.0006`.
A chronological causal replay reproduced the recorded probabilities and tested
smaller models. Per-mode calibration after 18 resolved mode shots achieved
Brier skill `+0.0081` and separation `+0.00045`; power subsegments were negative
and the old quality dimension added no benefit because its thresholds collapsed
nearly all Dynamic Cluster shots into one band. The mode-only model became the
next revalidation candidate but was rejected by the following run. No Phase 5
behavior was enabled.

### Phase 4 revalidation: run `20260715-213040`

The fresh 12-round run passed the instrumentation checks: the audit reported
zero issues, all 709 engine-accepted bullets had utility records, and there were
no duplicate or unstaged accepts. Utility outcomes covered 707/709 shots; the
two remaining bullet IDs (`19` and `112`) were still in flight in the final
round when the defeated process terminated and are finalized as EOF misses by
the summary. The supported posterior appeared for 706 shots, including 633
per-mode predictions.

Calibration still failed the predeclared directional gate. Predicted hit rate
was 14.6% versus 15.2% observed, but Brier skill against the fixed prior was
`-0.0106` and hit/miss probability separation was `-0.0038`. Offline causal
replay tested global-only updates, per-mode support thresholds from 30 through
100, stronger priors, and end-of-round updates. All learned variants remained
negatively discriminative on this run. A fixed 14% estimate was stable across
the two runs but had zero discrimination, so it is not a sufficient learned
calibration model and must not be used to claim this gate passed.

The mode-only implementation was rejected rather than retained as a promotion
candidate. The next calibration revision had to be selected using multi-run or
otherwise held-out evidence rather than another parameter search on one
12-round result. Phase 5 remained blocked.

### Phase 4 calibration revision: held-out Dynamic quality

Cross-run diagnosis found that the model had removed its only stable shot-level
predictor. Dynamic Cluster's configured `0.35/0.55` diagnostic thresholds
classified essentially every accepted surfer shot as `weak`. At the actual
scale, `solution_quality >= 0.10` was consistently useful:

- run `20260715-211503`: 7/33 high-quality hits versus 86/716 other shots;
- run `20260715-213040`: 20/60 high-quality hits versus 88/649 other shots.

The pooled odds ratio is about `2.80`, with a lower 95% bound near `1.74`.
Use the rounded conservative `1.75x` odds multiplier over the causal global
posterior; do not use the fitted central estimate. Strict staged replay preserves
the real ready-opportunity snapshot and delayed accepted-fire callback. It gives
Brier skill/separation `+0.0120/+0.0007` on the first run and
`+0.0126/+0.0092` on the second. The same feature also remained positive when
trained on either run and scored on the other, while gun mode alone did not.

This is retrospective candidate-selection evidence, not a fresh validation.
Keep the revised model shadow-only and require a separately approved telemetry
run to pass the existing contract before Phase 4 or Phase 5 advances.

The retrospective calculation is reproducible with the production calibrator,
including staged opportunity snapshots and an independent reset for each run:

```sh
tools/fire_utility_replay.py \
  battle-results/runs/20260715-211503/telemetry \
  battle-results/runs/20260715-213040/telemetry \
  --bot adaptive-prime \
  --json-output battle-results/fire-utility-replay.json
```

The replay must remain a model-selection diagnostic. The validation gate below
is scored from the probabilities recorded during a new live battle.

### Phase 4 validation contract

Any approved telemetry revalidation is an instrumentation and calibration gate,
not a behavior-promotion run. Save all four machine-readable reports:

```sh
run=battle-results/runs/<run>

tools/telemetry_audit.py "$run/telemetry" \
  --require-bot adaptive-prime \
  --json-output "$run/telemetry-audit.json"

tools/combat_economics_summary.py "$run" \
  --json-output "$run/combat-economics.json"

tools/gun_eval_summary.py "$run/telemetry" \
  --bot adaptive-prime \
  --json-output "$run/gun-eval.json"

tools/fire_utility_summary.py "$run/telemetry" \
  --bot adaptive-prime \
  --json-output "$run/fire-utility.json"
```

Pass the instrumentation gate only when the audit has zero issues, utility
accepted-shot coverage is `100%`, there are no duplicate accepted shots or
unstaged accepts, and any utility-resolution shortfall is limited to explained
terminal process truncation reconciled by durable bullet events. Report, but do
not tune from, groups with fewer than `30` resolved shots. Phase 4 may advance
only if supported fallback levels appear after the prior-only warm-up and the
prequential diagnostics are directionally useful: non-negative Brier skill
against the fixed prior and non-negative hit/miss probability separation. If
either is negative, keep utility shadow-only and revise calibration before any
Phase 5 behavior flag.

### Phase 4 fresh validation: run `20260715-220126`

The separately approved 12-round live run passed the contract with the revised
model still shadow-only. The telemetry audit reported zero issues, all `713`
engine-accepted bullets had exactly one utility record and final outcome, and
supported global predictions appeared on `710/713` shots. The Dynamic quality
fallback appeared on `41` supported shots.

Predicted hit rate was `16.1%` versus `15.7%` observed. Brier skill against the
fixed prior was `+0.00087` and hit/miss probability separation was `+0.00582`.
The positive margin is modest, so it does not justify additional calibration
complexity, but both predeclared directional checks passed. Phase 4 is complete
and the model remains the fixed input for the isolated Phase 5 experiments.
The battle also supplied the current telemetry attribution baseline: `713`
accepted shots, `112` hits, `0.77` average accepted power, about `0.80` average
hit power, `0.519` damage per accepted shot, `0.672` damage per fired energy,
`649` inferred enemy shots, and `100%` real enemy-hit-to-wave match coverage.

### Exit gate

- Reliability summaries compare predicted probability bands with real outcomes.
- Overall calibration is directionally useful, and diagnostic range/power
  slices reveal no material inversion at supported sample sizes.
- Sparse gun modes fall back safely to global evidence or the prior.
- Live fire behavior remains unchanged.

## Phase 5: Isolated Fire Behavior Experiments

### Experiment A: fire or hold at current power

Use the current policy-selected power and current same-mode aim. Change only the
decision to fire or hold based on calibrated utility.

Preserve existing safety and tactical rules, including stale-solution,
alignment, critical-energy, last-stand, and finisher semantics. Do not create an
unconditional `p >= 1.3` or similar confidence bypass; that makes the gate
circular and prevents calibration from evaluating expensive shots.

#### Rejected pre-A/B candidate

The first default-off candidate kept the existing fire gate authoritative,
waited for `30` resolved shots, fired at non-negative energy-swing utility,
preserved critical-energy/last-stand/finisher shots, and forced one probe after
at most the selected shot's cooldown interval. Its zero threshold was the
physical break-even point rather than a fitted parameter.

The two-round telemetry smoke (`20260715-223552`) failed the readiness gate
decisively, so no performance A/B was run. After `31` warm-up fires, an early
low global hit rate moved the shared base posterior below break-even. The bot
then emitted `678` utility-negative holds and only `22` cooldown probes,
accepted `62` shots, hit `2`, and lost score `9-291`. The audit's fire-reason
errors also confirmed that experimental fire reasons would have required a
schema contract change before any larger run.

This is a model-resolution failure, not a threshold-tuning opportunity. Outside
the positive Dynamic-quality flag, every ordinary opportunity shares the same
global probability, so any threshold becomes a battle-wide on/off switch rather
than shot selection. The flag, live gate, probe state, experimental reasons,
and schema field were removed. Do not retry Experiment A until a separately
validated negative shot-level predictor exists.

### Experiment B: choose among supported powers

Run only after Experiment A is decided. Compare a small set of powers already
supported by current policy. Every candidate must be re-aimed in the same gun
mode through a side-effect-free evaluation path before utility comparison.

Do not:

- impose a dynamic minimum-power floor;
- let the selector choose a different gun during candidate evaluation;
- reuse one bearing for powers with materially different flight time;
- combine this experiment with movement changes.

Experiment B is deferred with Experiment A. The validated model has no
power-conditioned hit probability, so score utility would mechanically prefer
more damage while energy utility would choose boundary powers from a shared
global probability. That is not supported power selection. Require held-out
power-dependent calibration before implementing this path.

### Exit gate

Each experiment gets its own baseline/candidate A/B and telemetry explanation.
Promote only if the economics improvement is repeatable, score remains within
its predeclared bound, and the apparent gain is not just lower firing volume or
one gun disappearing from selection.

## Deferred Work

### Selector calibration

Gun switching is a separate decision layer. Revisit it after combat-ledger and
fire-utility data are stable, using the
[damage-calibrated selector plan](confidence-calibrated-virtual-selector-plan.md).
That plan must be revalidated against this document before implementation; any
dependency on a universal `CombatRegime` is obsolete.

### Anti-surfer gun

The anti-surfer aim model remains governed by the
[anti-surfer safety-surface rebuild plan](gun-anti-surfer-safety-surface-rebuild.md).
Do not fold its hypotheses into PIF or use it to hide poor selector calibration.

### Movement anti-repetition

Defer anti-repetition penalties until telemetry proves that repeated bins,
directions, or transitions concentrate real enemy hits. A vague preference for
novel movement is not enough evidence for a live term.

## Validation Workflow

### Unit and repository checks

For shared math, profiles, or telemetry schemas:

```sh
PYTHONPATH=bots .venv/bin/python -m pytest
```

For every telemetry phase:

```sh
scripts/run-battle.sh \
  --rounds 12 \
  --telemetry \
  bots/adaptive-prime \
  bots/ports/basic-gf-surfer-port

tools/telemetry_audit.py \
  battle-results/runs/<run>/telemetry \
  --require-bot adaptive-prime

tools/fire_utility_summary.py \
  battle-results/runs/<run>/telemetry \
  --bot adaptive-prime
```

### Performance A/B

Performance comparisons must use distinct baseline and candidate worktrees or
repository references and must leave telemetry off:

```sh
scripts/run-ab.sh \
  --name <experiment> \
  --preset adaptive-1v1-basic-gf-surfer-port \
  --baseline <baseline-worktree> \
  --candidate <candidate-worktree> \
  --rounds 24 \
  --repeats 3
```

Do not compare one dirty tree with itself through `run-ab.sh`. Use
`run-battle-series.sh` when estimating variance for one current tree. Ask for
explicit approval before any planned batch totaling 50 or more rounds.

Keep diagnostic telemetry runs separate from performance runs. Telemetry is for
attribution; telemetry-free A/Bs are for promotion.

### Opponent matrix

- Primary focused gate: Python Basic GF Surfer port.
- Release smokes: `1-8` rounds against a small non-surfer selection from the
  local core bots.
- Converted legacy bots: optional parity or diagnostic evidence only.

### Promotion rules

Before an A/B begins, record numeric bounds derived from Phase 0 variance. A
candidate is promotable only when:

- its primary economics metric improves in at least two of three repeats;
- score share and first places remain inside the predeclared regression bound;
- the telemetry run explains the causal path;
- reduced shot volume or disappearance of one gun does not hide the result;
- telemetry audits and relevant tests pass;
- temporary experiment flags and rejected branches are removed.

## Implementation Order

```text
0. current-main baseline and variance
1. telemetry-only combat ledger
2. shadow movement-evidence split
3. isolated enemy-hit danger movement A/B
4. shadow fire-utility calibration
5. fire/hold A/B at current power
6. discrete same-mode power-choice A/B
7. selector work under its dedicated plan
8. anti-surfer work under its dedicated plan
```

Do not advance merely because a phase is implemented. Advance only after its
exit gate is met.

## Model and Reasoning Guidance

- Use **Sol with Extra High reasoning** for architecture changes, plan
  revalidation, movement evidence semantics, and fire-utility design.
- Use **High reasoning** for bounded implementation phases once their design and
  exit gate are fixed.
- Use **Medium reasoning** only for mechanical schema, documentation, or test
  updates after the design is frozen.
- Do not use Ultra as the default implementation mode. These phases are
  sequential, share state, and require evidence from one phase before the next
  can be designed safely.

## Success Definition

This plan succeeds when:

- the current combat-economics problem is confirmed with current-main evidence;
- accepted-shot, damage, energy, and enemy-fire accounting reconcile;
- real-hit movement evidence is no longer conflated with occupancy or uncertain
  expected pressure;
- a promoted movement change reduces enemy bullet damage without an unexplained
  offensive collapse;
- a promoted fire change improves damage or energy exchange without hiding
  behind reduced shot volume;
- focused surfer gains survive small non-surfer release smokes;
- no dead flags, old formulas, or compatibility residue remain.

### Current conclusion

The accounting, evidence-separation, and shadow-calibration goals are complete.
The live-promotion goals are not: the split-evidence movement candidate worsened
enemy damage in all three repeats, and the first fire/hold candidate failed its
telemetry smoke before A/B. Those candidates and their flags were removed, so
the cleaned tree deliberately retains the existing live movement and fire
policies.

Execution therefore stops at a safe shadow-only foundation rather than claiming
the plan's full success definition. A future fire experiment requires a
held-out negative shot-level predictor; a power experiment additionally
requires power-conditioned hit probability. Release smokes establish that the
cleaned tree still runs against ordinary opponents, not that a rejected live
candidate produced a gain.

## Stop Conditions

Stop and reassess when any of these occurs:

- Current-main evidence no longer shows the historical economics problem.
- Enemy fires or real hits cannot be attributed reliably enough to train the
  proposed profile.
- A candidate wins only against the focused port and materially regresses the
  non-surfer release smoke.
- An apparent gain comes from a different gun mix or firing volume rather than
  the behavior under test.
- Three independent live behavior hypotheses fail after trustworthy shadow
  instrumentation; revisit the architecture instead of adding more terms.
