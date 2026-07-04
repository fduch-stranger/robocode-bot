# BasicGFSurfer Python Parity Plan

This plan covers making `bots/ports/basic-gf-surfer-port` behave closer to the
fixed Java `BasicGFSurfer` reference opponent while still remaining a native
Python Tank Royale bot.

## Problem

The fixed Java legacy bot is not a normal source-level port. It runs the
original Robocode `AdvancedRobot` strategy through `robocode-api-bridge`, using
a generated wrapper and compatibility jars:

- `robocode-api-bridge.jar`
- `robocode-api-0.5.0.jar`
- `robocode-tankroyale-bot-api-0.32.1.jar`
- `robots-wrapper-0.3.1.jar`

The wrapper loads `wiki.BasicGFSurferFixed`, applies
`RobotMethodReplacer.transformRobotClass(...)`, and then runs the bot through
`BotPeer`. That bridge maps Tank Royale events into classic Robocode concepts
such as `ScannedRobotEvent`, `StatusEvent`, `setAhead`, `setBack`, `setFire`,
custom `Condition` events, and classic-style command staging.

The Python bot is a native rewrite using `robocode_tank_royale` 1.0.2. It copies
the strategy shape, but it does not run behind the Java Robocode compatibility
facade. As a result, near-identical formulas can still produce materially
different movement, wave timing, and survival behavior.

## Evidence

Direct 12-round matchup, fixed Java legacy bot versus current Python port:

| Bot | Score | Survival | Bullet Damage | First Places |
| --- | ---: | ---: | ---: | ---: |
| `BasicGFSurferFixed 1.02-local` | 1087 | 450 | 467 | 8 |
| `BasicGFSurfer Port 1.0` | 691 | 150 | 465 | 4 |

The bullet damage is nearly equal, while survival and first-place score are
lower for Python. That points primarily at movement and command/event semantics,
not raw aim quality.

## Goal

Build a narrow Python parity layer for this bot, not a full Robocode bridge.
The target is behavior close enough that the Python bot can be used as a stable
local non-legacy surfer opponent, while the Java fixed bot remains the stronger
reference until parity is demonstrated.

## Non-Goals

- Do not recreate the full Java `robocode-api-bridge` in Python.
- Do not change shared bot-core movement or gun systems for this port.
- Do not tune Adaptive Prime or other bots as part of this work.
- Do not optimize for elegance over parity; this bot is intentionally a legacy
  benchmark port.

## Implementation Status

Status on 2026-07-04: Phases 1 through 5 have a first implementation pass in
`bots/ports/basic-gf-surfer-port`, but Phase 6 has not passed the promotion
gate and parity is not proven.

Implemented:

- The port README now points parity work at the local fixed Java source and
  generated wrapper behavior, not Robowiki source alone.
- `_set_back_as_front` now emits distance-style `set_forward(100)` /
  `set_back(100)` commands instead of writing `target_speed` directly.
- The radar loop now uses staged radar turns for both search and lock, and only
  resumes search after scans go stale. This avoids the native port overwriting
  scan-lock radar commands with continuous search every tick.
- The port uses a single `_lateral_direction` for movement fallback and gun
  guess-factor sign, matching the fixed Java bot's shared direction state.
- Gun waves remain manually advanced; later inspection showed the Python API
  does expose custom events, so a closer `GFTWave` condition port is still open
  Phase 4 work. The remaining mismatch is more specific than timing alone:
  Java tracks a `GFTWave` after `setFire(...)` when energy is sufficient, while
  the Python port currently tracks a wave only when native `set_fire(...)`
  returns accepted, which can reduce gun-learning samples under gun heat.
- Explicit round-started and round-ended handlers reset per-round state while
  preserving battle-persistent surf and gun stats.

Validation so far:

| Check | Result |
| --- | --- |
| Focused port unit tests | `21 passed, 6 subtests passed` |
| Full unit suite | `304 passed` |
| Direct 12-round Java fixed vs Python port | Python `968`, Java fixed `942` |
| Direct 24-round Java fixed vs Python port | Java fixed `2397`, Python `1643` |
| Direct 12-round after radar fix | Java fixed `1141`, Python `1015` |
| Direct 24-round after radar fix | Python `2045`, Java fixed `1897` |
| Adaptive vs Java fixed, 24 rounds | Adaptive `2270`, Java fixed `1636` |
| Adaptive vs Python port, 24 rounds | Adaptive `2023`, Python `1367` |

Interpretation:

- The movement-command fix materially improved the short direct matchup.
- The radar-command fix removed a native-port radar conflict where search spin
  could overwrite scan-lock commands. The latest 24-round direct match is the
  first run showing rough direct parity with the fixed Java bot.
- Short samples are still noisy; use the Python port as the normal local surfer
  opponent for Adaptive tuning, and keep the fixed Java bot as a parity
  reference only.
- Remaining parity work is focused on custom-event gun-wave timing and fire-gate
  semantics, longer validation, and any GUI-observed stuck or round-reset
  behavior that repeats after the radar fix.
- The `24 x 3` parity gate below is still useful before claiming the port is
  strength-equivalent to the fixed Java reference.

## Phase 1: Pin The Reference

Use the embedded source from `wiki.BasicGFSurferFixed_1.02.jar` as the canonical
reference for parity checks.

Tasks:

- Extract or inspect `wiki/BasicGFSurferFixed.java` from the local fixed jar.
- Record the exact wrapper behavior:
  - generated `Wrapper.java`
  - `RobotMethodReplacer.transformRobotClass(...)`
  - `BotPeer` event mapping
- Keep the existing Java fixed bot alias, `--legacy basic-gf-surfer`, as a
  reference opponent for port parity checks only.
- Add a short note to the port README that parity work should compare against
  the fixed Java source, not against Robowiki source alone.

Exit criteria:

- The plan or bot README identifies the local fixed Java source and wrapper as
  the parity source of truth.

## Phase 2: Restore Movement Command Semantics

The current Python port uses continuous `target_speed = +/-8` in
`_set_back_as_front`. The fixed Java bot uses classic distance commands:

- `setAhead(100)`
- `setBack(100)`
- `setTurnRightRadians(...)`
- `setTurnLeftRadians(...)`

This is the highest-priority parity gap because the score difference is mostly
survival.

Tasks:

- Replace Python `_set_back_as_front` movement output with
  `set_forward(100)` / `set_back(100)` equivalents.
- Keep the turn commands as pending staged commands before `go()`.
- Preserve Java angle conversion explicitly so the function remains readable:
  Java radians strategy angle -> Tank Royale degrees -> native turn command.
- Add unit tests for all four Java branches:
  - forward/right turn
  - forward/left turn
  - back/right turn
  - back/left turn
- Add a regression test showing `_set_back_as_front` no longer writes
  continuous `target_speed` directly.

Exit criteria:

- Unit tests prove `_set_back_as_front` emits distance-style movement.
- A short parity battle against `--legacy basic-gf-surfer` shows the Python bot
  still boots and avoids obvious wall-stall regressions.

## Phase 3: Rejoin Legacy Direction State

The fixed Java bot uses one static `lateralDirection` for both fallback movement
orientation and gun guess-factor sign. The Python port currently separates
movement and gun direction.

That split is defensible for a new bot, but it is not parity. Because fallback
movement uses this value when no surf wave exists, it can change survival even
if the gun remains similar.

Tasks:

- Replace `_move_direction` and `_gun_lateral_direction` with one
  `_lateral_direction` field for the parity variant.
- On enemy scan, update `_lateral_direction` from enemy lateral velocity exactly
  where Java updates `lateralDirection`.
- On wall/stationary escape, invert `_lateral_direction` exactly where Java
  does.
- Use `_lateral_direction` for both fallback orbit orientation and gun wave
  offset.
- Adjust or remove tests that enforced split direction behavior.

Exit criteria:

- Unit tests assert wall escape, stationary escape, and gun offset all share the
  same direction field.
- Gun damage in short direct Java-vs-Python match remains roughly comparable to
  the current port, while survival does not regress.

## Phase 4: Align Gun Wave Timing

The Java fixed bot adds a `GFTWave` custom event after `setFire(...)` and lets
the event queue call `GFTWave.test()`. The Python port updates gun waves from
the main `run()` loop.

This can create one-turn timing drift and different learning order. A later
source/API audit found a second mismatch: the Java source calls `setFire(...)`
and then adds `GFTWave` when `getEnergy() >= BULLET_POWER`, whereas the native
Python port only adds a `GunWave` when `set_fire(BULLET_POWER)` returns `True`.
Because native `set_fire()` rejects shots while gun heat is positive, the
Python port likely records fewer gun-learning waves than the Java bridge path.

Tasks:

- Check whether native Python `Condition`/custom events can reasonably model
  `GFTWave.test()`.
- If yes, move gun-wave advancement into a custom condition-style callback.
- Align wave tracking gate with the Java source:
  - call/stage fire intent in the same order as Java,
  - track a gun wave when energy is sufficient, matching the Java
    `getEnergy() >= BULLET_POWER` gate,
  - separately document or test any native API rejection caused by gun heat.
- If no, keep manual wave updates but align ordering to Java:
  - scan handler creates wave
  - fire is attempted
  - wave tracking uses the Java energy gate unless validation proves native
    fire-accepted gating gives closer bridge behavior
  - wave advancement happens once per tick before the next scan-dependent aim
- Add tests for the order around `set_fire`, wave creation, and wave arrival.

Exit criteria:

- No wave is added when energy is insufficient; native gun-heat rejection is
  handled according to the chosen Java-parity gate.
- Wave tracking gate intentionally matches the Java fixed source, or battle
  evidence documents why native fire-accepted gating is closer to the bridge.
- Wave distance advances once per turn, not once per event burst.
- Short direct Java-vs-Python match shows no collapse in bullet damage.

## Phase 5: Round Lifecycle Parity

The Java bridge creates classic-like robot lifecycle behavior and the fixed
source calls `resetRoundState()` on `onRoundEnded`. Python currently resets from
`on_game_started` and turn-number rollback detection.

Tasks:

- Add explicit `on_round_started` / `on_round_ended` handlers if available in
  the Python API.
- Reset per-round instance state at the same lifecycle points as the Java fixed
  bot.
- Preserve battle-persistent stat buffers:
  - surf stats
  - gun stat buffers
- Test that per-round wave/location/state fields reset while stat buffers
  survive.

Exit criteria:

- Multi-round unit or integration test verifies reset boundaries.
- No round-2 stale-wave behavior in telemetry/battle logs.

## Phase 6: Validation Matrix

Use battle tests in tiers. Keep telemetry off unless investigating a specific
behavioral failure.

Smoke:

```sh
scripts/run-battle.sh --rounds 1 bots/ports/basic-gf-surfer-port --legacy basic-gf-surfer
scripts/run-ab.sh --name surfer-port-smoke --preset adaptive-1v1-basic-gf-surfer-port --rounds 1 --repeats 1
```

Direct parity:

```sh
scripts/run-battle.sh --rounds 12 bots/ports/basic-gf-surfer-port --legacy basic-gf-surfer
scripts/run-battle.sh --rounds 24 bots/ports/basic-gf-surfer-port --legacy basic-gf-surfer
```

Reference opponent:

```sh
scripts/run-battle.sh --rounds 24 bots/adaptive-prime --legacy basic-gf-surfer
scripts/run-battle.sh --rounds 24 bots/adaptive-prime bots/ports/basic-gf-surfer-port
```

Promotion gate:

```sh
scripts/run-ab.sh --name surfer-port-parity --preset adaptive-1v1-basic-gf-surfer-port --rounds 24 --repeats 3
```

Success criteria:

- Python port direct score versus Java fixed bot improves from the observed
  `691 / 1087` baseline toward rough parity.
- Bullet damage stays comparable to Java fixed bot.
- Survival and first-place share improve materially.
- No recurring stuck/wall-stall rounds appear in short direct battles.
- Full unit suite passes.

## Risks

- Exact parity may be impossible because the Java bridge uses a different
  client API version and a classic compatibility facade.
- Native Python event timing can still differ from Java `Condition` dispatch.
- Rejoining direction state may improve parity but make the bot less clean as a
  native Python design.
- Short battle samples are noisy; survival conclusions need repeated runs.

## Recommended First Patch

Start with Phase 2 only: replace continuous speed in `_set_back_as_front` with
distance-style `set_forward(100)` / `set_back(100)` and test it. This is the
smallest high-signal change and directly targets the observed survival gap.
