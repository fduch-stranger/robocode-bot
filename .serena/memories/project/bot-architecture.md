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
- Fire gating keeps normal energy reserves, but bots use a shared `last_stand` path for fresh, close, tightly aligned low-energy shots that leave a tiny reserve. Avoid reviving the removed Adaptive-specific low-energy override; it was too brittle and could leave Adaptive passive.
- `FireContext` carries distance/firepower buckets, flight time, lateral direction/confidence, wall escape balance, movement tags, and related diagnostics through waves and visits.
- Traditional GF has one production model for every bot: a global profile plus `(flight time, absolute lateral speed, wall margin)` segments, `8/36` linear blending, max-bin selection, smoothing `1.25`, decay `0.985`, and 31 bins. Superseded coarse profiles, alternate keys, density peaks, source centering, experiment presets, and their environment variables were removed. In the promotion evidence, this model beat the former global-only baseline in all three 24-round Python BasicGFSurfer repeats on hit rate, damage per shot, damage per fired energy, and mean absolute GF error. A later unchanged-selector compatibility check found Traditional GF was not starved but observed 172 fired-mode transitions over 36 rounds. Root-cause tracing showed Adaptive's Dynamic Cluster shot-quality power scaling called the stateful selector a second time and could leave a discarded speculative mode active. Adaptive now uses a side-effect-free same-mode re-aim. An eight-round two-gun smoke still found 47 real fired-mode transitions, so Adaptive's switch margin was changed once from `0.035` to `0.08`; the identical-format smoke dropped to 32 transitions while Traditional GF retained 23.9% of non-fallback shots. Do not continue broad selector tuning before forced Dynamic Cluster revalidation.
- Dynamic Cluster Python-surfer revalidation started with a clean 24-round forced baseline: 1,558 Dynamic shots, 170 hits (10.91%), mean power 0.62, damage/shot 0.282, signed/absolute GF error -0.161/0.549, and mean shot quality 0.047. A short no-quality-power screen showed the power policy materially suppresses shot power but was too noisy to promote. The opt-in `ROBOCODE_<BOT>_DYNAMIC_PRESET=simple_knn` control uses fixed 0.18 bandwidth, best-bin aim, no ambiguity centering, no context weighting, and disabled shot-quality scaling. A two-repeat 24-round-per-side confirmation rejected it: current hit 101/1,182 (8.55%), damage/shot 0.405, absolute GF error 0.601; simple hit 83/1,131 (7.34%), damage/shot 0.384, absolute GF error 0.596. A later 17-vs-25-neighbor screen also found lower error but lower hit rate at 25, so neither simple_knn nor 25 neighbors advances. Dynamic experiment knobs cover min/blend samples, neighbors, decay half-life, minimum effective samples, and GF bins. Production remains `current` with 17 neighbors; next ablate one context/density term at a time.
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
- Shared combat regime should be a common vocabulary with per-system adapters, not one giant hard segment key. Dynamic Cluster uses it softly, Traditional GF uses its fixed compact segment key, Displacement uses candidate bonuses, movement uses own-risk regimes, and fire EV uses profitability/danger.
- Compatibility is not a goal by itself. Remove old selector/fire/movement branches when a shared replacement wins cleanly and preserves necessary force-test/diagnostic hooks.

Environment hooks:
- Gun pinning: global `ROBOCODE_GUN_MODE`, per-bot `ROBOCODE_ADAPTIVE_GUN_MODE`, `ROBOCODE_CHASE_GUN_MODE`, `ROBOCODE_CIRCLE_GUN_MODE`, `ROBOCODE_SWEEP_GUN_MODE`.
- Selectable sets: global `ROBOCODE_GUN_SET`, per-bot `ROBOCODE_<BOT>_GUN_SET`.
- Eval waves: `ROBOCODE_ADAPTIVE_GUN_EVAL`, `ROBOCODE_CHASE_GUN_EVAL`, `ROBOCODE_CIRCLE_GUN_EVAL`, `ROBOCODE_SWEEP_GUN_EVAL`, plus matching `_INTERVAL` vars.

Do not duplicate formulas across docs. Keep exact math in `docs/bot-core-data-structures.md`; overview docs should link there.
