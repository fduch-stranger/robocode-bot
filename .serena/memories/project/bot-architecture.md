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
- Traditional GF has one production model for every bot: a global profile plus `(flight time, absolute lateral speed, wall margin)` segments, `8/36` linear blending, max-bin selection, smoothing `1.25`, decay `0.985`, and 31 bins. Superseded coarse profiles, alternate keys, density peaks, source centering, experiment presets, and their environment variables were removed. In the promotion evidence, this model beat the former global-only baseline in all three 24-round Python BasicGFSurfer repeats on hit rate, damage per shot, damage per fired energy, and mean absolute GF error. A later unchanged-selector compatibility check found Traditional GF was not starved but observed 172 fired-mode transitions over 36 rounds. Root-cause tracing showed Adaptive's Dynamic Cluster shot-quality power scaling called the stateful selector a second time and could leave a discarded speculative mode active. Adaptive now uses a side-effect-free same-mode re-aim. An eight-round two-gun smoke still found 47 real fired-mode transitions, so Adaptive's switch margin was changed once from `0.035` to `0.08`; the identical-format smoke dropped to 32 transitions while Traditional GF retained 23.9% of non-fallback shots. After forced Dynamic Cluster revalidation, a 20-round live Python-surfer trace found mature Dynamic-to-Linear re-entry produced a 0/14 long-range batch and Traditional GF shots at `|GF| = 0.933` went 0/11. Adaptive now requires a `0.18` adjusted-score margin for fallback-over-primary switches, and Traditional GF bounds firing to `|GF| <= 0.87` while retaining full-range training. Six-round exploratory controls rejected changing Linear aim itself: normal Linear scored 362 versus wall-aware 280, an 18-degree cap 247, and head-on 77. The Traditional GF cap improved its forced smoke from score 305 to 338 and hit rate 10.2% to 11.8%; the normal-selector smoke kept 4/6 firsts but score fell 435 to 365, so these results are directional rather than a promotion-grade gate.
- Dynamic Cluster was revalidated against the clean Python BasicGFSurfer port in forced one-gun tests. The simple KNN bundle and 25-neighbor candidate were rejected; the temporary `simple_knn` preset and its `bot.config` status field were removed. Individual screens retained context weighting, centroid refinement, ambiguity centering, and adaptive hit-width bandwidth. Disabling shot-quality power scaling also regressed score and hit rate, so it remains enabled despite weak confidence calibration. The false optimization was an effective 30-to-150-sample warm-up multiplier that pulled selected GF toward zero. Shortening it to 30-to-60 samples won both a two-repeat 24-round aim-policy confirmation (score 3029→3410, hit rate 11.80%→12.86%, damage/energy 0.578→0.604) and the matching production-power confirmation (score 2787→3136, hit rate 11.92%→15.40%, damage/energy 0.505→0.651); all telemetry audits passed. The exact direct-aim behavior for samples 30-to-59 was not separately benchmarked; full removal was accepted as a cleanup extrapolation without the third production-policy repeat. The blend behavior, environment knob, and decision-context field were removed. Production now uses selected density aim directly after `min_samples`, with 17 neighbors and the existing context/density extractor. Do not use mean absolute GF error alone as a promotion proxy; it slightly worsened in the winning production confirmation.
- Displacement uses rotation-normalized replay with continuous speed/lateral/advancing/wall/heading-change similarity and density-supported replay clusters. The former order-2 Markov weighting was removed after two independent 12-round forced pairs against the Python BasicGFSurfer port: across 24 rounds per configuration, density-only improved score 1699→1856, PIF hit rate 12.0%→12.7%, and PIF damage/shot 0.618→0.675. A second two-pair isolation removed the discrete coarse-match bonus, improving score 1857→1994, PIF hit rate 11.8%→12.5%, and damage/shot 0.680→0.720. The prior optimizations relied on the converted legacy surfer or duplicated continuous inputs.

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
- Shared combat regime should be a common vocabulary with per-system adapters, not one giant hard segment key. Dynamic Cluster uses it softly, Traditional GF uses its fixed compact segment key, Displacement uses continuous candidate similarity, movement uses own-risk regimes, and fire EV uses profitability/danger.
- Compatibility is not a goal by itself. Remove old selector/fire/movement branches when a shared replacement wins cleanly and preserves necessary force-test/diagnostic hooks.

Environment hooks:
- Gun pinning: global `ROBOCODE_GUN_MODE`, per-bot `ROBOCODE_ADAPTIVE_GUN_MODE`, `ROBOCODE_CHASE_GUN_MODE`, `ROBOCODE_CIRCLE_GUN_MODE`, `ROBOCODE_SWEEP_GUN_MODE`.
- Selectable sets: global `ROBOCODE_GUN_SET`, per-bot `ROBOCODE_<BOT>_GUN_SET`.
- Eval waves: `ROBOCODE_ADAPTIVE_GUN_EVAL`, `ROBOCODE_CHASE_GUN_EVAL`, `ROBOCODE_CIRCLE_GUN_EVAL`, `ROBOCODE_SWEEP_GUN_EVAL`, plus matching `_INTERVAL` vars.

Do not duplicate formulas across docs. Keep exact math in `docs/bot-core-data-structures.md`; overview docs should link there.
