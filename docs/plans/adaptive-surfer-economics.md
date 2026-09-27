# Adaptive Prime Surfer Economics

Follow-up to the [Adaptive Prime roadmap](adaptive-prime-roadmap.md). The
roadmap's items are complete; this plan uses the telemetry of the finished bot
to pick the next levers against the BasicGFSurfer port.

## Measured Baseline

One 24-round telemetry battle of current `main` against the port
(`battle-results/runs/jev-m3-prime-control`, 2026-09-27):

| Metric | Adaptive Prime | BasicGFSurfer port |
| --- | ---: | ---: |
| Shots | 1347 | 1202 |
| Hit rate | 14.4% | 10.9% |
| Mean firepower | 0.83 | 1.9 (fixed) |
| Bullet damage | 655 | 1216 |
| Rounds won | 17 | 7 |
| Score | 1740 | 1741 |

What the telemetry says about how rounds are decided:

- Rounds last about 830 turns and end with both bots near zero energy. The
  surfer fires power 1.9 below its own break-even hit rate, so most of its
  energy loss is self-inflicted; our bullets take only about 27 of its 100
  energy per round.
- 82% of our shots are fired at 400-600 px, where every gun hits about 13%.
  Under 400 px the hit rate is 18-36%, but only 17% of shots are fired there.
  The duel movement policy prefers 580 px and keeps at least 430 px.
- Dynamic Cluster's shot-quality power scaling reported `very_weak` on 100% of
  its firing ticks, so against this opponent it is a constant 0.55x power
  multiplier. Dynamic Cluster fired 69% of our shots at mean power 0.66 while
  the other guns averaged 1.25 from the same firepower policy.
- Score counts bullet damage 1:1 and a round win at about 65 points, so the
  2x bullet-damage gap is the largest measurable gap between the two bots.

## Experiments

Each experiment runs on its own branch and PR, in order, from the merged
`main` of the previous step. The port is never modified.

| # | Experiment | Change | Expected effect |
| --- | --- | --- | --- |
| 1a | Firepower: scaling off | `ROBOCODE_ADAPTIVE_DYNAMIC_SHOT_QUALITY_POWER_SCALING=0`, env only | Bullet damage up if the hit rate holds at higher power; risk is losing the attrition war |
| 1b | Firepower: far band | `DuelFirepowerPolicy` `far_base_power` 1.0 to 1.3, `far_strong_power` 1.3 to 1.6, `very_far_power` 0.8 to 1.0 | Same lever, milder step under the default scaling |
| 1c | Firepower: energy-gated scaling | Scaling applied only at or below 40 own energy (a temporary knob on the experiment branch, not merged) | Keep 1a's damage gain while firing cheap shots in the endgame |
| 2 | Distance | `DuelMovementPolicy` `preferred_distance` 580 to 480, `min_distance` 430 to 380; fallback 530 and 400 | Higher hit rate for both bots; sign unknown |
| 3 | Anti-surfer gun | Second Dynamic Cluster variant `anti_surfer` with recency weighting and about 7 neighbors, selectable by the virtual-gun system | A few points of hit rate; gated on a telemetry battle before any A/B |

## Protocol

- `scripts/run-ab.sh --preset adaptive-1v1-basic-gf-surfer-port`, 24 rounds,
  telemetry off, nothing else CPU-heavy running, one benchmark at a time.
- Six candidate runs. The baseline is current `main`, pooled with the roadmap's
  existing runs for the same code and topped up to at least six runs.
- Primary metric is Adaptive Prime's score. First places, bullet damage, and
  damage taken are reported alongside. Hit rate needs telemetry, so it is only
  available from separate telemetry battles.
- A win means the candidate's mean beats the pooled baseline by at least two
  standard errors of the difference. Smaller gains are neutral, and tuning
  changes are not merged on neutral.
- Experiment 3 must first pass a 24-round telemetry gate: its production
  wave-visit score and real hit rate at or above `dynamic_cluster`'s in
  `tools/gun_eval_summary.py`, and no turn-time regression in
  `tools/turn_timing_summary.py`.

## Results

Experiment 1 verdict: every firepower variant converts Adaptive's accuracy edge
into more bullet damage, and every one of them loses rounds, so none clears
the score gate. The endgame attrition is decided by energy spent per shot, and
the cheap shots the scaling produces are what win it. Nothing was merged.

Per 24-round run, mean ± standard error. The baseline row pools every run of
the same code: the roadmap's 3 hot-gun-tracking runs (1824 ± 76) and the 6
baseline runs of each firepower A/B (1625 ± 107, 1735 ± 113, 1586 ± 57).
Their spread is a reminder that a single 3-run A/B cannot see changes under
about 15%. The z values compare each variant with the full pooled baseline.

| # | Variant | Runs | Score | First places | Damage dealt | Damage taken | Decision |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| - | Baseline `main` (hot-gun tracking) | 21 | 1674 ± 49 | 16.3 | 609 ± 16 | 1327 ± 17 | - |
| 1a | Scaling off | 6 | 1746 ± 52 | 15.0 | 746 ± 32 | 1227 ± 29 | Neutral, not merged: score +4% (z 1.0); damage dealt +22% (z 3.9) and damage taken -8% (z -3.0), but rounds won -8% (z -1.5). More power drains the surfer faster and loses the endgame attrition. |
| 1b | Far band | 6 | 1563 ± 56 | 13.7 | 666 ± 24 | 1344 ± 33 | Negative, not merged: score -7% (z -1.5), rounds won -16% (z -3.3), damage dealt +9% (z 2.0). |
| 1c | Energy-gated scaling (40) | 6 | 1749 ± 115 | 14.7 | 769 ± 41 | 1242 ± 63 | Neutral, not merged: score +5% (z 0.6); damage dealt +26% (z 3.6), damage taken -6% (z -1.3), rounds won -10% (z -1.2). Gating the cheap shots to the endgame did not recover the lost rounds. |
| 2 | Distance | - | - | - | - | - | pending |
| 3 | Anti-surfer gun | - | - | - | - | - | pending |
