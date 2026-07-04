# Legacy Bot Porting Guideline

This guideline describes how to port converted legacy Robocode bots into native
Python Tank Royale bots under `bots/ports/`. It is based on the
`basic-gf-surfer` porting work, where a source-level rewrite looked similar to
the Java bot but behaved differently because the Java reference ran through an
old compatibility bridge.

Use this document when a legacy opponent is useful enough to become a stable
local benchmark. Keep the Java legacy bot as a historical reference, but tune
and benchmark normal project work against the native Python port once it has
passed the validation gates below.

## Core Principle

Port the behavior contract, not only the formulas.

Many converted legacy bots run through `robocode-api-bridge` and compatibility
jars such as:

- `robocode-api-bridge.jar`
- `robocode-api-0.5.0.jar`
- `robocode-tankroyale-bot-api-0.32.1.jar`
- `robots-wrapper-0.3.1.jar`

That bridge maps Tank Royale events into classic Robocode concepts such as
`ScannedRobotEvent`, `StatusEvent`, `setAhead`, `setBack`, `setFire`, custom
`Condition` events, and classic command staging. A native Python bot using
`robocode_tank_royale` does not get the same lifecycle, command queue, or event
timing for free.

Treat every port as a small compatibility project. Do not assume matching math
is enough.

## When To Port

Port a legacy bot when:

- it is a recurring tuning opponent,
- the Java bridge version is noisy, stale, hard to run, or glitchy,
- the bot teaches a strategy class the local bots need to face,
- the port can remain self-contained under `bots/ports/<name>`.

Do not port a bot just to hide a weak benchmark. If the legacy reference is
unreliable, document that unreliability and validate the native port against
clean samples.

## Non-Goals

- Do not recreate the full Java `robocode-api-bridge` in Python.
- Do not change shared `bots/bot_core/` behavior unless the port exposes a
  general bug in shared code.
- Do not tune Adaptive Prime or other production bots as part of the port.
- Do not optimize for a cleaner architecture at the cost of legacy behavior.

## Porting Workflow

### 1. Pin The Reference

Before changing Python behavior, identify the real reference being ported.

Tasks:

- Locate the converted bot directory or jar selected by `--legacy <name>`.
- Inspect the embedded original source when available.
- Inspect wrapper behavior, including generated wrapper classes and bridge
  method replacement.
- Record compatibility API versions and any local patches.
- Add a bot README note naming the source/wrapper as the parity source of
  truth.

Exit criteria:

- The port README identifies the local source and compatibility wrapper used as
  the reference, not only the public Robowiki page or original bot name.

### 2. Build The Native Bot Shell

Put the port in `bots/ports/<bot-name>/` with the normal bot manifest and
launcher.

Tasks:

- Add `<bot-name>.json`, `<bot-name>.sh`, `<bot-name>.py`, and `README.md`.
- Keep bootstrap code local to the port only when the Tank Royale GUI launches
  the `.py` file directly.
- Make the launcher use the repo Python environment like other bots.
- Add a manifest/launcher unit test.

Exit criteria:

- `scripts/run-battle.sh --rounds 1 bots/ports/<bot-name> <other-bot>` boots.
- Direct GUI launch can find repo dependencies or re-exec through `.venv` when
  needed.

### 3. Align Movement Command Semantics

Classic Robocode movement commands are distance commands, not just desired
speed. For example, Java `setAhead(100)` / `setBack(100)` is not equivalent to
writing `target_speed = +/-8` forever.

Tasks:

- Translate classic `setAhead`, `setBack`, `setTurnRightRadians`, and
  `setTurnLeftRadians` into staged Tank Royale commands.
- Preserve angle-system conversion explicitly:
  Java radians strategy angle -> Tank Royale degrees -> native turn command.
- Add tests for all movement branches, including forward/back and left/right
  turns.
- Add regression tests proving the port does not bypass command semantics with
  direct speed assignment unless the legacy behavior truly did that.

Exit criteria:

- Unit tests prove branch-level movement command parity.
- A short battle shows the port boots and does not wall-stall immediately.

### 4. Preserve Shared Legacy State

Legacy bots often reuse one field for multiple subsystems. Splitting that state
can be a good native design but still break parity.

Tasks:

- Find state fields used by both movement and targeting.
- Preserve shared direction, last velocity, energy, wave buffers, and stat
  buffers when they affect behavior.
- Only split state when validation shows the split is intentionally better and
  the README documents the difference.

Exit criteria:

- Tests assert shared state is updated and consumed by all legacy-equivalent
  subsystems.
- Short battles show gun damage and survival do not regress.

### 5. Align Radar And Scan Freshness

Native loops can overwrite event-driven radar locks if search commands run
every tick after scan handlers.

Tasks:

- Stage radar search and lock commands in the same order each tick.
- Keep recent scan locks intact for a short grace period.
- Resume search only after scans go stale.
- Test search-before-scan, lock-preservation, and stale-scan recovery.

Exit criteria:

- The bot does not spin radar over fresh scan locks.
- Short battles do not show repeated scan loss or round cycling caused by radar
  starvation.

### 6. Align Gun Waves And Fire Gates

Classic bots commonly use custom `Condition` events to advance gun waves. Native
Python code might instead update waves from the main loop. These are not
automatically equivalent.

Tasks:

- Identify whether the Java source tracks waves after fire intent, energy
  checks, accepted fire, or custom events.
- Test the native Python API behavior around rejected fire, gun heat, and
  insufficient energy.
- Prefer native accepted-fire tracking when bridge-style energy-only tracking
  creates waves for shots that the native API rejects.
- Advance waves once per turn, not once per event burst.
- Record rejected alternatives with battle evidence.

Exit criteria:

- No wave is tracked for insufficient energy.
- Gun-heat rejection is handled by the chosen parity rule.
- Unit tests cover accepted fire, rejected fire, wave arrival, wave removal, and
  once-per-turn advancement.
- Short battles show no collapse in bullet damage.

### 7. Align Round Lifecycle

Bridge wrappers can emulate classic lifecycle callbacks that differ from native
Python event order.

Tasks:

- Add explicit round-started and round-ended handlers when the Python API
  provides them.
- Reset per-round waves, locations, energy, command freshness, and temporary
  movement state at round boundaries.
- Preserve battle-persistent stat buffers that the legacy bot kept across
  rounds.
- Keep a turn-number rollback guard if it protects GUI or runner differences.

Exit criteria:

- Tests verify per-round state resets while battle-persistent stats survive.
- Multi-round battles show no stale-wave or stale-location behavior in later
  rounds.

### 8. Validate With Clean Evidence

Use tiers and do not treat raw Java-reference wins as proof when the Java bridge
bot glitches.

Smoke:

```sh
scripts/run-battle.sh --rounds 1 bots/ports/<bot-name> --legacy <legacy-name>
scripts/run-ab.sh --name <bot-name>-smoke --preset <port-preset> --rounds 1 --repeats 1
```

Direct parity:

```sh
scripts/run-battle.sh --rounds 12 bots/ports/<bot-name> --legacy <legacy-name>
scripts/run-battle.sh --rounds 24 bots/ports/<bot-name> --legacy <legacy-name>
```

Repeat parity:

```sh
scripts/run-battle-series.sh --runs 3 --rounds 24 bots/ports/<bot-name> --legacy <legacy-name>
```

Sampled motion sanity for bridge glitches:

```sh
scripts/run-battle-series.sh \
  --runs 3 \
  --rounds 24 \
  --run-dir battle-results/series/<bot-name>-motion-sanity-3x24 \
  --tick-sample 10 \
  bots/ports/<bot-name> \
  --legacy <legacy-name>

tools/bot_motion_sanity.py \
  battle-results/series/<bot-name>-motion-sanity-3x24 \
  --bot <LegacyReferenceBotName> \
  --json-output battle-results/series/<bot-name>-motion-sanity-3x24/motion-sanity.json \
  --warn-only

tools/bot_motion_sanity.py \
  battle-results/series/<bot-name>-motion-sanity-3x24 \
  --bot <NativePortBotName> \
  --json-output battle-results/series/<bot-name>-motion-sanity-3x24/port-motion-sanity.json \
  --warn-only
```

Success criteria:

- The native port improves materially from the first observed baseline.
- Bullet damage is comparable to or better than the legacy reference on clean
  rounds.
- Survival and first-place share improve materially.
- The port has no recurring stuck or wall-stall rounds in sampled checks.
- Java-reference rounds where the bridge bot stays alive but stops moving are
  flagged as suspect and excluded from clean parity claims.
- Full unit suite passes.

## Tooling Rules

- Prefer `scripts/run-battle-series.sh` for repeat validation against one
  current worktree.
- Use `scripts/run-ab.sh` only for real baseline/candidate comparisons with
  separate worktrees or refs.
- Keep telemetry off for performance validation unless investigating telemetry
  behavior.
- Do not use legacy-specific accuracy filters to discard high-accuracy native
  port rounds.
- Ask before spending `50+` rounds unless the user has already approved that
  run.

## BasicGFSurfer Case Study

`bots/ports/basic-gf-surfer-port` is the first completed application of this
guideline.

Reference:

- Legacy alias: `--legacy basic-gf-surfer`
- Reference source: embedded `wiki.BasicGFSurferFixed.java` from the local fixed
  legacy setup
- Bridge behavior: generated wrapper plus `RobotMethodReplacer` and `BotPeer`
  compatibility mapping

Important mismatches found:

- Distance-style movement commands mattered more than direct speed assignment.
- Continuous radar search overwrote fresh scan locks in the native loop.
- Java used one lateral direction field for both movement fallback and gun
  guess-factor sign.
- Native custom-event-style gun waves performed worse than manual once-per-turn
  updates.
- Java-style energy-only wave tracking also performed worse than native
  accepted-fire tracking.
- The fixed Java bridge bot can stay alive while effectively immobile, inflating
  raw Python port score.

Final selected behavior:

- Distance-style `set_forward(100)` / `set_back(100)` movement.
- Staged radar search/lock with recent-scan grace.
- Shared `_lateral_direction`.
- Native fire-accepted gun-wave tracking.
- Explicit once-per-turn gun-wave advancement.
- Explicit round-started and round-ended resets, preserving battle-persistent
  surf and gun stats.

Final validation on 2026-07-04:

| Check | Result |
| --- | --- |
| Focused port unit tests | `23 passed, 6 subtests passed` |
| Full unit suite | `321 passed` |
| Sampled 3x24 fixed Java motion sanity | Suspect; `62` clean rounds score Python `5744`, Java fixed `4224`; `10` immobile Java rounds contributed Python `1770`, Java fixed `0` |
| Sampled 3x24 Python port motion sanity | OK; `72` rounds, `0` suspect rounds, longest stationary span `10` sampled turns |
| Sampled 3x24 raw aggregate | Python `7514`, Java fixed `4224`; bullet damage Python `4070`, Java fixed `2565`; first places Python `48`, Java fixed `25` |
| A/B smoke | Passed with `adaptive-1v1-basic-gf-surfer-port`, `1` round, `1` repeat |

Interpretation:

- The Python port is not byte-for-byte or event-for-event identical to the Java
  bridge bot.
- It is the preferred stable local BasicGFSurfer-style opponent.
- Raw wins over the Java bridge bot must be discounted when the Java bot is
  immobile.
- The clean subset still supports using the Python port as the normal local
  surfer benchmark.

## Port README Checklist

Every port README should state:

- the legacy alias and source of truth,
- whether the port is a benchmark, parity reference, or experimental opponent,
- known bridge/API mismatches,
- validation commands and latest clean evidence,
- whether legacy Java runs need motion sanity or other filters,
- which project tooling preset should use the port.
