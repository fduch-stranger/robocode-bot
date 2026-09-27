# Tomcat Port

Python Tank Royale port of `lxx.Tomcat 3.68` (Alexey "jdev" Zhidkov, 2013), a
wave-surfing duelist with the Tomcat Claws replay gun. It is a strong local
sparring partner: much stronger than the BasicGFSurfer port and, so far,
stronger than Adaptive Prime.

## Source Of Truth

- Behavior is ported from the Java source embedded in
  `lxx.Tomcat_3.68.jar` (`robot.java.source.included=true`, build of
  2013-07-29, mode `normal`). Every decision-making class was ported;
  painting, key handling, the movement/targeting challenge modes, the debug
  plugins, and the time profiler were dropped.
- The bridge-wrapped Java bot (`--legacy lxx.Tomcat_3.68`, imported with
  `import-legacy-bots.sh`) is **not** a usable parity reference. Through the
  bridge it fails class transformation for `lxx.Tomcat`, throws
  `Snapshot skipped` on most turns (its turn log never chains, so its gun runs
  blind), and dies on `DeathEvent`. It lost 2 of 3 rounds to Adaptive Prime,
  which the native port beats 10 of 10.
- The port is an experimental opponent, not a benchmark yet: the roadmap and
  A/B baselines stay on the BasicGFSurfer port until this bot has enough
  pooled runs of its own.

## Layout

```text
tomcat-port.py          Tank Royale boundary: events in, commands out, turn loop
tomcat_port/
  lxx_utils.py          angles, rules, points, BattleField, intervals, averages
  snapshots.py          RobotSnapshot, MySnapshot, EnemySnapshot, RobotImage
  waves.py              Wave, WaveManager
  bullets.py            LXXBullet, BulletSnapshot, shadows, prediction data
  targeting.py          Target, TargetData, TargetManager, engine event records
  ts_log.py             TurnSnapshot, TurnSnapshotsLog, the 21 attributes
  data_analysis.py      kd-tree (nearest and range search), data points
  enemy_gun_model.py    AdvancedEnemyGunModel: 31 logs per enemy, best-log selection
  enemy_bullets.py      EnemyBulletManager: fire detection, shadows, future bullets
  my_bullets.py         BulletManager: own bullets and waves
  movement.py           WaveSurfingMovement, PointsGenerator, PointDanger, DistanceController
  gun.py                TomcatClaws, the five data views, TomcatEyes
  strategies.py         StrategySelector: find enemies, fatality, duel, win
  office.py             per-round wiring and StatisticsManager
```

## Tank Royale Differences And How They Are Handled

- **Angles and coordinates.** All ported math stays in Robocode radians (0 up,
  clockwise). Tank Royale directions are converted at the boundary with
  `tank_degrees_to_java_radians`. Positions are the same in both engines.
- **Turn loop and event order.** Java ran status and scan events, then the
  loop body. Tank Royale dispatches a turn's events inside `go()`, so the loop
  builds the status snapshot first, replays last turn's fire event, fans the
  tick out to the managers in the Java listener order, then decides. Scan
  events are queued by the target manager and consumed on the tick, as in
  Java.
- **Movement commands.** Tomcat set a per-turn body turn rate, a maximum
  velocity, and `setAhead(100 * sign)`. The port maps those to
  `set_turn_left`, `max_speed`, and `set_forward` each turn, including the
  Robocode 1.6.1.4 workaround that stops before reversing.
- **Firing.** `setFireBullet` returned the bullet at once; Tank Royale reports
  it next turn in `BulletFiredEvent`. The port records an accepted `set_fire`
  and creates the wave and `LXXBullet` at the next turn from the previous
  snapshots, exactly where Java did, then matches later bullet events by
  bullet id instead of position.
- **Events.** Tank Royale gives absolute enemy coordinates, so the scanned,
  ram, and bullet-hit positions are used directly instead of being projected
  from bearings. Bullet-hit-wall stands in for `BulletMissedEvent`.
- **Hit detection.** Tomcat's own wave checks keep the 36x36 square; the
  engine decides real hits with its 18 px circle. Minor and deliberate.
- **Data structures.** Rednaxela's kd-tree and Tomcat's R-tree are replaced by
  one bucketed kd-tree with nearest-neighbour and range search; the heap sort
  became an ordinary sort by round time. `QuickMath` lookup tables became
  `math` calls.
- **Battle-persistent state.** Java kept static maps across rounds (target
  data, enemy gun logs, targeting profiles, hit rates, gun data views). They
  are module-level stores reset on `GameStartedEvent`.
- **Per-turn cost.** Tomcat is heavy: the median turn is about 0.25 ms, but the
  enemy gun model's log updates, the second-wave movement search, and the gun's
  replay reach 20-160 ms on a few turns per battle, which the engine counts as
  skipped turns (about 8-9 per 24 rounds on this machine). The bot keeps its
  previous commands on those turns.

## Validation

```sh
scripts/run-battle.sh --rounds 1 bots/ports/tomcat-port bots/adaptive-prime
scripts/run-battle.sh --telemetry --rounds 24 bots/ports/tomcat-port bots/ports/basic-gf-surfer-port
tools/turn_timing_summary.py battle-results/runs/<run>/telemetry --bot tomcat-port
scripts/run-battle-series.sh --runs 1 --rounds 24 --tick-sample 10 \
  --run-dir battle-results/series/tomcat-port-motion-sanity-1x24 bots/ports/tomcat-port bots/adaptive-prime
tools/bot_motion_sanity.py battle-results/series/tomcat-port-motion-sanity-1x24 --bot "Tomcat Port" --warn-only
PYTHONPATH=bots .venv/bin/python -m pytest tests/test_tomcat_port.py
```

Evidence on 2026-09-27 (first native runs, telemetry on):

| Opponent | Rounds | Tomcat Port | Opponent | Notes |
| --- | ---: | ---: | ---: | --- |
| Adaptive Prime | 10 | 1390, 10 firsts, 658 damage | 205, 0 firsts, 205 damage | no port errors |
| BasicGFSurfer port | 24 | 2400, 23 firsts, 835 damage | 574, 1 first, 501 damage | 8 skipped turns |
| Adaptive Prime (motion sanity) | 24 | 2869 clean | 856 clean | 24 clean rounds, no stall |

The bridge-wrapped Java Tomcat scored 174 to Adaptive Prime's 279 over 3
rounds, so Java-reference parity battles are not a meaningful gate for this
bot; the native port is validated against the local bots and by its unit
tests instead.

Telemetry is observation-only: with `--telemetry` the port emits
`bot.turn_timing` (with `phase_us` for status, listeners, movement, gun, and
commands) and `bot.skipped_turn`.
