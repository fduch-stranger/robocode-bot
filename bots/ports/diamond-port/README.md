# Diamond Port

Python Tank Royale port of `voidious.Diamond 1.8.28` (Voidious, 2009-2012), the
long-time top-three RoboRumble bot: wave surfing over dynamic-clustering danger
estimates in 1v1, minimum-risk movement in melee, and a virtual-gun array
(TripHammer KNN, Anti-Surfer, Perceptual, Main and Melee guns). It is the
strongest local opponent: it beats the Tomcat port, Adaptive Prime and the
BasicGFSurfer port by wide margins.

## Source Of Truth

- Behavior is ported from the Java source embedded in
  `voidious.Diamond_1.8.28.jar` (`robot.include.source=true`, built
  2012-10-01 against Robocode 1.7.3.2). Every decision-making class was
  ported: `DiamondEyes` (radar), `DiamondWhoosh` with `SurfMover`,
  `MeleeMover`, `MoveDataManager` and `MoveEnemy` (movement), `DiamondFist`
  with `GunDataManager`, `GunEnemy`, `VirtualGunsManager` and the five guns
  (gun), the shared `Wave`, `WaveManager`, `MovementPredictor`, `KnnView`,
  `RobotStateLog` and geometry, and the genetic-string decoder that seeds the
  perceptual gun. Painting, key handling, the error logger, the targeting and
  movement challenge modes, and the two rare alternative colour schemes were
  dropped.
- Rednaxela's kd-tree (`ags.utils.KdTree.WeightedSqrEuclid` with its size
  limit) and the third-generation tree behind the perceptual gun are replaced
  by one bucketed kd-tree in `kd_tree.py` with the same bucket size, split
  rule, weighted squared distances and oldest-point eviction.
- The bridge-wrapped Java Diamond (`--legacy diamond`) was never a usable
  reference (see `docs/tooling.md`); the port is validated against the local
  bots and by its unit tests.
- The port is an experimental opponent, not a benchmark: the roadmap and A/B
  baselines stay on the BasicGFSurfer port. Do not tune it; change it only to
  fix its fidelity to the original, and say so.

## Layout

```text
diamond-port.py         Tank Royale boundary: RobotAdapter, events in, commands out, turn loop
diamond_port/
  dia_utils.py          Rules, angle utils, Point, BattleField, RobotState(Log), Interpolator, geometry
  kd_tree.py            bucketed weighted kd-tree with size limit (Rednaxela stand-in)
  knn_view.py           KnnView: one tree plus k, weight, thresholds and decay
  movement_predictor.py Robocode-order movement physics and precise escape angles
  wave.py               Wave, WaveManager, bullet shadows, precise intersections
  enemy.py              Enemy, EnemyDataManager, scan and bullet records
  gun.py                DiamondFist, GunDataManager, GunEnemy, VirtualGunsManager, the guns, formulas
  move.py               DiamondWhoosh, MoveDataManager, MoveEnemy, SurfMover, MeleeMover, formulas
  radar.py              DiamondEyes
  perceptual_dna.py     the evolved 1000-point tree of the perceptual gun, as its hex DNA string
```

## Tank Royale Differences And How They Are Handled

- **Angles and coordinates.** All ported math stays in Robocode radians (0
  up, clockwise). `RobotAdapter` converts Tank Royale directions at the
  boundary and gives the components the `AdvancedRobot` getters Diamond used.
  Positions are the same in both engines; scanned, ram and bullet positions
  come straight from the events instead of bearing-and-distance projection.
- **Turn loop and event order.** Diamond ran `move.execute()`,
  `gun.execute()`, `radar.execute()`, then `execute()`. Tank Royale dispatches
  a turn's events inside `go()`, and its event priorities (bot death, bullet
  hit bullet, bullet hit bot, hit by bullet, scanned bot) match Robocode's
  order, so the same loop reproduces the Java sequence.
- **Movement commands.** `setBackAsFront` (turn plus `setAhead(100)` or
  `setBack(100)`) and `setMaxVelocity` map to `set_turn_left`, `set_forward`
  and `max_speed` each turn. Diamond's own `getMaxVelocity()` field, which a
  fresh robot instance reset to 0 every round, is mirrored in the adapter.
- **Firing.** `setFireBullet` returned the bullet at once; `set_fire` returns
  acceptance and the bullet appears next turn. The port marks firing waves and
  notifies the movement's bullet-shadow model on acceptance, exactly where
  Java did.
- **Scan energy lag.** Tank Royale scans report an enemy's energy before the
  turn's bullet hits and hit bonuses are applied, one turn later than
  Robocode. Diamond adjusted its tracked enemy energy at event time, so the
  port queues our bullet damage and the enemy's hit bonus and applies them
  after the tick's scan has been read; otherwise a hit would either mask a real
  shot or be read as one. Wall damage reaches the same scan in both engines and
  keeps Diamond's heuristic.
- **Physics order.** The predictor keeps Diamond's Robocode order (turn, then
  accelerate, then move); Tank Royale moves then turns, a few pixels per tick
  of difference in the surfer's self-prediction. Its own wave checks keep the
  36x36 square; the engine decides real hits with its 18 px circle.
- **Guards.** Three places where Java would have thrown (an empty precise
  intersection, a missing interpolated state for the imaginary wave, and a
  missing state when a firing wave is confirmed) skip or fall back instead of
  ending the round; they did not fire in any validation battle.
- **Battle-persistent state.** Java kept the radar, movement and gun objects in
  statics across rounds; the port creates them once per battle and calls their
  `init_round`. Enemies are keyed by Tank Royale bot id.
- **Per-turn cost.** Median turn about 2-3 ms (movement about 2 ms, gun about
  0.8 ms); the 99th percentile is 5 ms against Adaptive Prime and 20 ms
  against the BasicGFSurfer port, whose long-lived waves make the two-wave
  danger search and the 225-neighbour TripHammer aim expensive. A few turns
  per battle exceed the 30 ms budget (6 skipped turns in 24 rounds against
  the surfer port); the bot keeps its previous commands on those turns. The
  port calls `gc.freeze()` at every round start and raises the generation-2
  threshold, as the Tomcat port does.

## Validation

```sh
scripts/run-battle.sh --rounds 1 bots/ports/diamond-port bots/chase-lock
scripts/run-battle.sh --telemetry --rounds 24 bots/ports/diamond-port bots/ports/basic-gf-surfer-port
tools/turn_timing_summary.py battle-results/runs/<run>/telemetry --bot diamond-port
scripts/run-battle-series.sh --runs 1 --rounds 24 --tick-sample 10 \
  --run-dir battle-results/series/diamond-port-motion-sanity-1x24 bots/ports/diamond-port bots/adaptive-prime
tools/bot_motion_sanity.py battle-results/series/diamond-port-motion-sanity-1x24 --bot "Diamond Port" --warn-only
scripts/run-battle.sh --rounds 2 bots/ports/diamond-port bots/chase-lock bots/circle-strafer bots/sweep-pressure
PYTHONPATH=bots .venv/bin/python -m pytest tests/test_diamond_port.py
```

Evidence on 2026-09-27 (first native runs):

| Opponent | Rounds | Diamond Port | Opponent | Notes |
| --- | ---: | ---: | ---: | --- |
| Adaptive Prime (telemetry) | 3 | 370, 3 firsts | 35, 0 firsts | no errors, no skipped turns, p50 2.2 ms, p99 5.1 ms |
| Tomcat Port | 10 | 862, 8 firsts, 325 damage | 395, 2 firsts, 255 damage | |
| Adaptive Prime (motion sanity) | 24 | 3337, 24 firsts, 1581 damage | 362, 0 firsts | 24 clean rounds, no stall |
| Chase, Circle, Sweep (melee) | 2 | 597, 2 firsts | 266 / 234 / 138 | melee mover and melee gun paths |
| BasicGFSurfer port (telemetry) | 24 | 2514, 24 firsts, 895 damage | 423, 0 firsts | p50 3.3 ms, p99 20 ms, 6 skipped turns, no errors |

The A/B preset `adaptive-1v1-diamond-port` runs Adaptive Prime against this
port. Telemetry is observation-only: with `--telemetry` the port emits
`bot.turn_timing` (with `phase_us` for movement, gun and radar) and
`bot.skipped_turn`. `ROBOCODE_DIAMOND_PORT_VERBOSE=1` prints Diamond's
round-end gun ratings and hit percentages to stderr.
