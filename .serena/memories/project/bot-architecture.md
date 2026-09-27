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
- Adaptive uses side-effect-free same-mode re-aim after Dynamic Cluster power scaling (it rebuilds every gun's bearing at the new power, so it costs about as much as a full aim).
- Adaptive hot-gun tracking: the full aim and power re-aim run only from `full_aim_lead_turns` (3) turns before the gun can fire; otherwise the gun keeps the last full solution's offset from the direct bearing. This cut median decision time 4.7 -> 0.68 ms and skipped turns 10 -> 1 per 24 rounds, and won its A/B (+12%). Env: `ROBOCODE_ADAPTIVE_HOT_GUN_TRACKING=0` disables it.
- Dynamic Cluster bandwidth uses a degree hit angle over degree escape angles (min 0.10, max 0.30, scale 1.25; median ~0.117 against the surfer); before the fix it was always pinned at the old 0.12 floor. Scale 1.5 (median ~0.14) was -4.4%; a narrow variant (min 0.08, max 0.24, scale 1.0) performed like the chosen defaults.
- Selector gates every candidate against the current mode, independent of registry order.
- Adaptive requires a `0.18` adjusted-score margin for fallback-over-primary switches.
- Adaptive-specific tuning is centralized in `bots/adaptive-prime/adaptive_config.py`, including named firepower, target, radar, movement, movement-flattening, and minimum-risk policies/configs. Behavior methods should not carry independent tuning literals.
- Adaptive `bot.config` telemetry includes the complete effective configuration, profile name, and deterministic fingerprint. Coarse environment controls cover go-to surfing, flattener direction application, and gun-heat waves.

Validated gun state:
- Traditional GF uses one global profile plus `(flight time, absolute lateral speed, wall margin)` segments, `8/36` blending, max-bin selection, smoothing `1.25`, decay `0.985`, and 31 bins. Firing is bounded to `|GF| <= 0.87`; training retains the full range.
- Dynamic Cluster uses direct density aim after 30 samples, 17 neighbors, context weighting, centroid refinement, ambiguity centering, adaptive hit-width bandwidth, and shot-quality power scaling. The rejected long warm-up blend and its environment/status fields were removed.
- Against the BasicGFSurfer port the shot-quality scaling is a constant 0.55x (always `very_weak`). Turning it off, gating it by energy, and raising the far-band power all raised bullet damage but lost rounds in the endgame attrition (rejected 2026-09-27, `docs/plans/adaptive-surfer-economics.md`). Cheap late shots win the attrition; do not re-run plain firepower increases.
- Displacement uses rotation-normalized replay with continuous speed, lateral, advancing, wall, and heading-change similarity plus density-supported replay clusters. Markov and discrete coarse-match bonuses were removed.
- Wall-aware Linear was a losing control and has been removed.

Movement architecture:
- Shared movement covers enemy-fire waves, GF danger profiles, flattening, go-to surfing, actual bullet shadows, and minimum-risk movement.
- There is one production movement profile. The rejected split occupancy/hit/expected-pressure shadow model was removed.
- Movement prediction follows Tank Royale target-speed order: update speed, move on the previous direction, apply speed-limited turn, wall clip, then zero speed after collision.
- Bullet shadows use actual `BulletFiredEvent.bullet` state and apply to both direction and go-to surfing; `gun.fire_drift` audits planned versus actual bullet state.
- Engine turn order (1.3.1 `TurnProcessor`): fire guns (pre-move position, pre-rotation gun heading) -> move/turn -> wall and bot collisions -> scans -> advance all bullets one step -> bullet hits. So confirmed enemy waves start at turn E-1 from the previous position; our bullet hits and the enemy's 3x power hit bonus reach the next scan; wall and ram damage reach the same scan (`enemy_wall_hit_damage_bound`, `RAM_DAMAGE`).
- Rejected experiments (do not retry without new evidence): hit-width fire gate (neutral, holds fire), pre-aim toward the next-turn bearing (lower aim error but no A/B gain), melee priority radar for Adaptive (-17% melee: rescans starve the fresh-scan fire gate), GC freeze (no slow turn was GC-dominated).

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
