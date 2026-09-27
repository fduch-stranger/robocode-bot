# Adaptive Prime Roadmap

Goal: make Adaptive Prime stronger against the BasicGFSurfer port (the fixed
enemy benchmark), completing every item below except the Jev experiment.
Changes are promoted through A/B runs (`adaptive-1v1-basic-gf-surfer-port`,
24 rounds x 3, telemetry off, one benchmark at a time) and merged when
validated.

Benchmark noise: identical baseline code has scored 4248-5174 per 24x3 run, so
one A/B only reliably detects changes of roughly 10% or more. Correctness fixes
with a verified mechanism are kept when the A/B is not negative; tuning changes
need a clear A/B win.

## Status

| # | Item | Status | Evidence |
| --- | --- | --- | --- |
| 1 | Tank Royale 1.3.1 upgrade | Done (PR #1) | Tests, smoke battle, telemetry audit |
| 2 | Enemy-fire correction timing, enemy hit bonus, go-to bullet shadows | Done (PR #1) | Score 4835 -> 5045 (+4.3%), damage taken -7% |
| 3 | Gun selector independent of candidate order | Done (PR #1) | Neutral A/B, correctness fix |
| 4 | Machine-wide battle lock | Done (PR #1) | Unit tests |
| 5 | Dynamic Cluster bandwidth degree fix plus retune | In progress (separate session) | Centered variant 4708 -> 4907, bullet damage 555 -> ~633 per run |
| 6 | Enemy waves start at the bullet origin (turn E-1); wall and ram damage not read as fire | A/B running | Engine order verified in the 1.3.1 `TurnProcessor` |
| 7 | Slow-turn diagnostics (phase timing, GC pauses) | Committed, telemetry run queued | Needed to attribute skipped turns |
| 8 | Pre-aim the gun at next turn's solution | A/B queued | Bullets leave 2.2-2.5 degrees off plan today |
| 9 | Reduce turn-time spikes | Waiting for item 7 data | Quiet-machine outlier 27.5 ms vs 30 ms budget |
| 10 | Melee radar rescans all enemies; remove dead collision command | Melee A/B queued | Single-target lock starved minimum-risk movement |
| - | Rejected: hit-width fire gate | Dropped | Neutral; held fire instead of hitting more |
| - | Deferred: Jev advisor bot | Plan only | [Jev advisor bot plan](jev-advisor-bot.md); needs an API key |
