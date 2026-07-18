# Bot Architecture

All bots share reusable logic from `bots/bot_core/`. Prefer shared core changes
when behavior is genuinely common; keep bot personality and tuning in each bot
directory.

Canonical docs:
- `docs/bot-shared-systems.md`: shared control loop, radar, guns, movement, fire gate, and telemetry.
- `docs/bot-core-data-structures.md`: target snapshots, gun/movement waves, profiles, KNN buffers, and formulas.
- Bot READMEs: bot-specific strategy, policy, and tuning context.

Current bots:
- Adaptive Prime: 1v1 champion candidate using go-to surfing, potential-field fallback, and minimum-risk melee.
- Chase Lock: target-lock pressure bot.
- Circle Strafer: defensive orbital bot.
- Sweep Pressure: direct sweep-pressure bot.
- `bots/ports/basic-gf-surfer-port`: primary clean local surfer benchmark.

Gun architecture:
- `VirtualGunSystem` builds aim/fire context, evaluates registered components, tracks waves, scores visits, and emits diagnostics.
- Live modes are `linear`, `traditional_gf`, `dynamic_cluster`, and `displacement`.
- The force-testable-only control is `head_on`.
- `dynamic_cluster` is the primary KNN GF learner; `traditional_gf` and `displacement` are situational; `linear` and `head_on` are simple-motion fallbacks.
- `AimModeSelector` is sticky and role-aware. `gun.switch_decision` is the main selector diagnostic.
- `gun.eval_wave_visit` is selector-only evidence when enabled and must not train production gun models.
- Adaptive uses side-effect-free same-mode re-aim after Dynamic Cluster power scaling.
- Adaptive requires a `0.18` adjusted-score margin for fallback-over-primary switches.
- Adaptive-specific tuning is centralized in `bots/adaptive-prime/adaptive_config.py`, including named firepower, target, radar, movement, movement-flattening, and minimum-risk policies/configs. Behavior methods should not carry independent tuning literals.
- Adaptive `bot.config` telemetry includes the complete effective configuration, profile name, and deterministic fingerprint. Coarse environment controls cover go-to surfing, flattener direction application, and gun-heat waves.

Validated gun state:
- Traditional GF uses one global profile plus `(flight time, absolute lateral speed, wall margin)` segments, `8/36` blending, max-bin selection, smoothing `1.25`, decay `0.985`, and 31 bins. Firing is bounded to `|GF| <= 0.87`; training retains the full range.
- Dynamic Cluster uses direct density aim after 30 samples, 17 neighbors, context weighting, centroid refinement, ambiguity centering, adaptive hit-width bandwidth, and shot-quality power scaling. The rejected long warm-up blend and its environment/status fields were removed.
- Displacement uses rotation-normalized replay with continuous speed, lateral, advancing, wall, and heading-change similarity plus density-supported replay clusters. Markov and discrete coarse-match bonuses were removed.
- Wall-aware Linear was a losing control and has been removed.

Movement architecture:
- Shared movement covers enemy-fire waves, GF danger profiles, flattening, go-to surfing, actual bullet shadows, and minimum-risk movement.
- There is one production movement profile. The rejected split occupancy/hit/expected-pressure shadow model was removed.
- Movement prediction follows Tank Royale target-speed order: update speed, move on the previous direction, apply speed-limited turn, wall clip, then zero speed after collision.
- Bullet shadows use actual `BulletFiredEvent.bullet` state; `gun.fire_drift` audits planned versus actual bullet state.

Telemetry and analysis:
- Key events include `bot.config`, `track`, `gun.switch`, `gun.switch_decision`, `gun.wave_visit`, `gun.eval_wave_visit`, `gun.fire_drift`, `enemy.fire_detected`, `enemy.gun_heat_wave`, `movement.profile_visit`, `movement.flatten`, `movement.goto_surf`, `movement.minimum_risk`, `bullet.fired`, `bullet.hit_bot`, and `hit.bullet`.
- Use `tools/telemetry_audit.py` for schema and attribution checks, `tools/combat_economics_summary.py` for score/firepower/damage summaries, `tools/gun_eval_summary.py` for gun/selector diagnostics.
- The combat-economics movement and fire candidates were rejected. Their ledgers, calibrator, shadow scoring, telemetry, tools, tests, and plans were removed. Production movement, fire gate, and power policy remain unchanged.

Opponent policy:
- The Python BasicGFSurfer port is the supported surfer evidence target.
- Generic converted-Java support remains for unported references such as Diamond, DrussGT, and Saguaro.
- BasicGFSurfer-specific Java aliases and benchmark presets were removed.

Environment hooks:
- Gun pinning: global `ROBOCODE_GUN_MODE` and per-bot `ROBOCODE_<BOT>_GUN_MODE`.
- Selectable sets: global `ROBOCODE_GUN_SET` and per-bot `ROBOCODE_<BOT>_GUN_SET`.
- Eval waves: per-bot `ROBOCODE_<BOT>_GUN_EVAL` and matching `_INTERVAL`.

Do not duplicate formulas across docs. Keep exact math in
`docs/bot-core-data-structures.md`.
