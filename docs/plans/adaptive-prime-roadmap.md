# Adaptive Prime Roadmap

Goal: make Adaptive Prime stronger against the BasicGFSurfer port (the fixed
enemy benchmark). The original items are complete; later experiments are
appended, and [Adaptive Prime surfer economics](adaptive-surfer-economics.md)
holds the detailed record of items 11-16.
Changes are promoted through A/B runs (`adaptive-1v1-basic-gf-surfer-port`,
24 rounds x 6 candidate runs, telemetry off, one benchmark at a time), judged
against the pooled baseline below with `tools/ab_pool.py`, and merged on a win
of at least two standard errors of the difference.

Benchmark noise: identical baseline code has scored 4248-5174 per 24x3 run,
and six-run batches of the same code have averaged 1395-1735 per run, so a
single batch cannot see changes under about 15%. Correctness fixes with a
verified mechanism are kept when the A/B is not negative; tuning changes need
a clear win against the pooled baseline.

## Status

| # | Item | Status | Evidence |
| --- | --- | --- | --- |
| 1 | Tank Royale 1.3.1 upgrade | Done (PR #1) | Tests, smoke battle, telemetry audit |
| 2 | Enemy-fire correction timing, enemy hit bonus, go-to bullet shadows | Done (PR #1) | Score 4835 -> 5045 (+4.3%), damage taken -7% |
| 3 | Gun selector independent of candidate order | Done (PR #1) | Neutral A/B, correctness fix |
| 4 | Machine-wide battle lock | Done (PR #1) | Unit tests |
| 5 | Dynamic Cluster bandwidth degree fix plus retune | Done (PR #3) | Pooled A/B: mean score 4773 -> 5026, bullet damage per run 591 -> 638 |
| 6 | Enemy waves start at the bullet origin (turn E-1); wall and ram damage not read as fire | Done (PR #4) | A/B 4691 -> 4869, firsts 43 -> 47; vs pooled baseline: score +1.2%, damage taken -3.2%; engine order verified in the 1.3.1 `TurnProcessor` |
| 7 | Slow-turn diagnostics (phase timing, GC pauses) | Done (PR #2, PR #4) | `tools/turn_timing_summary.py` attributes slow turns to a phase or to GC |
| 8 | Pre-aim the gun at next turn's solution | Dropped | Lower aim error (median 1.48 -> 0.96 degrees) but no gain: 5 candidate runs 1567 ± 54 vs 6 pooled baseline runs 1641 ± 38 per run (-4.5%); damage dealt unchanged |
| 9 | Reduce turn-time spikes | Done (PR #5) | Root cause: the full aim and Dynamic Cluster re-aim ran every turn (no slow turn was GC-dominated). Hot-gun tracking: median turn 4.7 -> 0.68 ms, p99 20.7 -> 6.9 ms, skipped turns 10 -> 1 per 24 rounds; A/B 4888 -> 5472 (+12%), firsts 46 -> 53 |
| 10 | Melee radar rescans all enemies; remove dead collision command | Radar dropped; dead code removed (PR #5) | Melee A/B 12864 -> 10663 (-17%), firsts 25 -> 14: rescans starve the fresh-scan fire gate (`memory_turns` 1) |
| 11 | Firepower: Dynamic Cluster shot-quality scaling off | Rejected (neutral) | 6 runs vs 21-run pooled baseline: score +4% (z 1.0), bullet damage +22%, damage taken -8%, rounds won -8%; the scaling is a constant 0.55x vs the surfer. [Surfer economics](adaptive-surfer-economics.md) |
| 12 | Firepower: far-band power 1.3/1.6/1.0 | Rejected | Score -7% (z -1.5), rounds won -16% (z -3.3) |
| 13 | Firepower: scaling gated to own energy <= 40 | Rejected (neutral) | Score +5% (z 0.6), bullet damage +26%, rounds won -10% |
| 14 | Duel distance: preferred 480, minimum 380 | Rejected alone (neutral) | 6 runs vs 27-run pooled baseline: score +1% (z 0.3), rounds won +3%, damage unchanged |
| 15 | Anti-surfer gun: recency-weighted Dynamic Cluster variant | Rejected (neutral) | Gate passed on virtual wave score (+28%) but real hit rate unchanged (15.5% pinned); 12 runs: score +3% (z 0.6). Branch `claude/anti-surfer-gun`, not merged |
| 16 | Shot-quality scaling off by default plus duel distance 480/380 | Done (PR #13) | Each alone neutral; together 12 runs vs 57-run pooled baseline: score 1608 -> 1791 (+11%, z 3.3), bullet damage +24%, damage taken -17%, rounds won unchanged. [Surfer economics](adaptive-surfer-economics.md) |
| - | Rejected: hit-width fire gate | Dropped | Neutral; held fire instead of hitting more |
| - | Rejected: GC freeze at round boundaries | Not needed | No slow turn was GC-dominated |

## Pooled Results

Per 24-round run against the BasicGFSurfer port (mean ± standard error), pooling
every A/B side that ran the same bot code:

| Code | Runs | Score | First places | Damage dealt | Damage taken |
| --- | --- | --- | --- | --- | --- |
| Original (Tank Royale 1.0.2) | 6 | 1668 ± 59 | 67% | 619 ± 16 | 1315 ± 42 |
| + 1.3.1 and gun selector fix | 3 | 1612 ± 81 | 65% | 595 ± 32 | 1364 ± 34 |
| + fire-detection fixes | 15 | 1604 ± 56 | 64% | 607 ± 22 | 1348 ± 30 |
| + Dynamic Cluster fix | 6 | 1675 ± 68 | 66% | 638 ± 27 | 1358 ± 55 |
| + wave origin, wall/ram corrections | 3 | 1623 ± 56 | 65% | 605 ± 30 | 1305 ± 38 |
| Main before tracking (DC fix, wave origin) | 3 | 1629 ± 56 | 64% | 623 ± 41 | 1314 ± 73 |
| + hot-gun tracking (`main` before PR #13) | 57 | 1608 ± 29 | 64% | 605 ± 9 | 1353 ± 12 |
| main + shot-quality scaling off (env) | 6 | 1746 ± 52 | 63% | 746 ± 32 | 1227 ± 29 |
| main + far-band power 1.3/1.6/1.0 | 6 | 1563 ± 56 | 57% | 666 ± 24 | 1344 ± 33 |
| main + scaling gated to energy <= 40 | 6 | 1749 ± 115 | 61% | 769 ± 41 | 1242 ± 63 |
| main + duel distance 480/380 | 6 | 1674 ± 76 | 69% | 606 ± 16 | 1342 ± 47 |
| main + anti_surfer gun | 12 | 1689 ± 82 | 68% | 617 ± 13 | 1331 ± 52 |
| main + gun + scaling off + distance 480/380 | 6 | 1867 ± 118 | 66% | 816 ± 24 | 1161 ± 62 |
| + scaling off, distance 480/380 (current `main`, PR #13) | 12 | 1791 ± 47 | 65% | 753 ± 18 | 1122 ± 37 |

One run's score varies by about ±150, so a 3-run A/B detects only changes of
roughly 15% or more. Compare candidates against the pooled baseline and give
candidates 6 runs when a decision matters.
