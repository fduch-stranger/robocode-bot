# Bot Architecture

All bots share reusable logic from `bots/bot_core/`. Prefer shared core changes when behavior is generally useful; keep bot personality and tuning surfaces in each bot directory.

Canonical docs:
- `docs/bot-shared-systems.md`: shared control loop, targets/radar, virtual guns, fire gate, enemy-fire detection, movement, telemetry.
- `docs/bot-core-data-structures.md`: target snapshots, gun/movement waves, KNN/profile buffers, physics formulas, telemetry record shapes.
- Bot READMEs: bot-specific movement, firepower, gun policy, telemetry, tuning cues.
- `docs/plans/adaptive-combat-economics-plan.md`: active combat-economics direction.

Current bots:
- Adaptive Prime: 1v1 champion candidate. Uses go-to surfing when possible, potential-field fallback, minimum-risk in melee, and aggressive confidence/energy-based firepower.
- Chase Lock: target-lock pressure bot with range-band chase/orbit movement.
- Circle Strafer: stable defensive orbital bot with wall escape and separation.
- Sweep Pressure: direct sweeping pressure bot with projected wall avoidance.
- `bots/ports/basic-gf-surfer-port`: primary clean local surfer reference opponent for repeatable tuning.

Gun architecture:
- `VirtualGunSystem` is the shared facade. It builds `AimContext`/`FireContext`, asks registered gun components for bearings, tracks waves, scores virtual visits, updates component learners, and emits diagnostics.
- Live repo-bot modes are `linear`, `traditional_gf`, `dynamic_cluster`, and `displacement`. Standard force-testable modes also include `head_on`, `linear_wall_aware`, and `anti_surfer`.
- `dynamic_cluster` is the primary KNN GF learner. `traditional_gf`, `displacement`, and `anti_surfer` are situational. `linear`/`head_on` are fallback/simple-motion modes.
- `AimModeSelector` is sticky and role-aware through `GunModeTraits`, mode policy gates, confidence/source penalties, context bonuses, and optional eval-wave evidence. `gun.switch_decision` is the main selector diagnostic; `score` is adjusted, `raw_score` is unadjusted.
- `gun.eval_wave_visit` is neutral diagnostics and selector-only evidence when enabled; it must stay out of production gun learning.
- `FireContext` carries distance/firepower buckets, flight time, lateral direction/confidence, wall escape balance, movement tags, and related diagnostics through waves and visits.
- Traditional GF currently uses global, exact-segment, and coarse-segment profiles with source-aware penalties/centering. Treat it as under-modeled until forced-gun telemetry proves a better profile source.
- Displacement uses rotation-normalized replay with speed/lateral/advancing/wall/flight-time similarity, Markov weighting, and density-supported replay clusters.

Movement architecture:
- Shared movement code lives in `bots/bot_core/movement` and covers enemy-fire waves, GF danger buffers, movement flattening, go-to surfing, bullet shadows, and minimum-risk movement.
- Movement prediction should follow Tank Royale target-speed order: speed update, move on previous direction, turn by speed-limited rate, wall clip, zero speed after wall collision.
- Bullet shadows should use actual `BulletFiredEvent.bullet` state; `gun.fire_drift` audits planned-vs-actual bullet state.

Telemetry and analysis:
- Key events: `bot.config`, `track`, `gun.switch`, `gun.switch_decision`, `gun.wave_visit`, `gun.eval_wave_visit`, `gun.fire_drift`, `enemy.fire_detected`, `enemy.gun_heat_wave`, `movement.profile_visit`, `movement.flatten`, `movement.minimum_risk`, `bullet.fired`, `bullet.hit_bot`, `hit.bullet`.
- Use `tools/telemetry_audit.py` for schema/attribution checks, `tools/combat_economics_summary.py` for score/firepower/damage economics, and `tools/gun_eval_summary.py` for virtual-gun calibration and selector diagnostics.

Current strategic direction:
- Python BasicGFSurfer port is the primary clean surfer evidence target. Converted legacy surfer is parity/historical context only; accuracy filtering is legacy diagnostic context, not a normal promotion policy.
- Active plan is core combat economics: shared combat regime vocabulary, opponent combat profile, EV fire decisions, dynamic firepower floors, enemy-hit danger movement, anti-repetition movement, and later damage-aware gun selection/anti-surfer rebuild.
- Shared combat regime should be a common vocabulary with per-system adapters, not one giant hard segment key. Dynamic Cluster uses it softly, Traditional GF can use compact profile subsets, Displacement uses candidate bonuses, movement uses own-risk regimes, and fire EV uses profitability/danger.
- Compatibility is not a goal by itself. Remove old selector/fire/movement branches when a shared replacement wins cleanly and preserves necessary force-test/diagnostic hooks.

Environment hooks:
- Gun pinning: global `ROBOCODE_GUN_MODE`, per-bot `ROBOCODE_ADAPTIVE_GUN_MODE`, `ROBOCODE_CHASE_GUN_MODE`, `ROBOCODE_CIRCLE_GUN_MODE`, `ROBOCODE_SWEEP_GUN_MODE`.
- Selectable sets: global `ROBOCODE_GUN_SET`, per-bot `ROBOCODE_<BOT>_GUN_SET`.
- Eval waves: `ROBOCODE_ADAPTIVE_GUN_EVAL`, `ROBOCODE_CHASE_GUN_EVAL`, `ROBOCODE_CIRCLE_GUN_EVAL`, `ROBOCODE_SWEEP_GUN_EVAL`, plus matching `_INTERVAL` vars.

Do not duplicate formulas across docs. Keep exact math in `docs/bot-core-data-structures.md`; overview docs should link there.
