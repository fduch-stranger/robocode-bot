# Bot Architecture

All bots share reusable logic from `bots/bot_core/`. Prefer changing shared code when behavior is genuinely common; keep strategy/personality in the bot directory.

Canonical docs:
- `docs/bot-shared-systems.md`: common control loop, target cache, radar, virtual guns, gun learning, fire gate, enemy fire detection, movement learning, minimum risk movement, telemetry semantics.
- `docs/bot-core-data-structures.md`: target snapshots, gun waves, movement waves, rolling KNN memory, guess-factor profiles, stats buffers, enemy fire-power prediction, telemetry records, approximation tradeoffs.
- Bot-specific READMEs: bot state machines, movement mode choices, firepower policy, key telemetry, tuning checklist.

Current bot roles:
- Adaptive Prime: 1v1-first champion candidate. Uses go-to surfing when surfable waves exist, potential-field movement as fallback, minimum-risk in melee, and aggressive confidence/energy-based firepower.
- Chase Lock: pressure/chase bot. More target-lock oriented and can be weak if it tunnels stale targets or prioritizes pressure over dodge.
- Circle Strafer: stable defensive orbital bot with wall escape, separation, and conservative fire.
- Sweep Pressure: direct sweeping pressure bot with projected wall avoidance and steady close-range fire.

Gun architecture context:
- `VirtualGunSystem` is the shared gun facade. `AimModeSelector` owns sticky virtual-gun selection and can report `GunSwitchCandidate` diagnostics through `select_with_diagnostics()`.
- `gun.switch_decision` telemetry records sampled selector decisions/rejections: unavailable, visits, score floor, margin, superseded, selected, current, and forced.
- Adaptive Prime has bot-specific `GunPolicy` thresholds in `bots/adaptive-prime/adaptive_config.py`; do not copy them blindly to other bots.
- Adaptive live-selects linear, traditional GF, dynamic cluster, and anti-surfer. `displacement` is force-testable but not live-selectable unless future evidence supports it.
- Chase Lock, Circle Strafer, and Sweep Pressure currently use default shared `GunConfig`; they inherit shared selector mechanics but not Adaptive's tuned policy.

Telemetry event examples: `track`, `gun.switch`, `gun.switch_decision`, `gun.wave_visit`, `gun.eval_wave_visit`, `enemy.fire_detected`, `enemy.gun_heat_wave`, `movement.profile_visit`, `movement.flatten`, `movement.minimum_risk`, `bullet.fired`, `bullet.hit_bot`, `hit.bullet`.

Do not duplicate formulas across docs. Keep exact math in `docs/bot-core-data-structures.md`; overview docs should link there.