# Circle Strafer

Circle Strafer is the stable orbital bot. It keeps lateral motion around the
selected target, separates from close enemies, and avoids walls before doing
anything clever. It uses the shared virtual gun and movement learning systems,
but its own behavior is deliberately predictable and defensive.

Shared systems are documented in:

- [Shared Bot Systems](../../docs/bot-shared-systems.md)
- [Bot Core Data Structures](../../docs/bot-core-data-structures.md)

## What Makes It Different

- Constant lateral orbit is the default behavior.
- Close enemy separation has higher priority than aiming pressure.
- Wall escape is simple, conservative, and held until the bot is clearly away
  from the edge.
- 1v1 movement learning only changes orbit direction, with surf danger included
  in the direction choice.
- Melee uses minimum-risk movement when enough targets are known.

## Turn Flow

```mermaid
flowchart TD
    A["run loop"] --> B["wall or collision movement"]
    B --> C{"melee targets known?"}
    C -- "yes" --> D["minimum-risk destination"]
    C -- "no" --> E["orbit"]
    D --> F["select target"]
    E --> F
    F --> G["apply 1v1 flattener"]
    G --> H["aim and radar lock"]
    H --> I["fire if allowed"]
```

## Movement State

```mermaid
stateDiagram-v2
    [*] --> Orbit
    Orbit --> WallAvoid: "near wall"
    WallAvoid --> Orbit: "clear"
    Orbit --> Separate: "enemy too close"
    Separate --> Orbit: "distance restored"
    Orbit --> MinimumRisk: "multiple targets"
    MinimumRisk --> Orbit
    Orbit --> FlattenedOrbit: "direction flip"
    FlattenedOrbit --> Orbit
```

## Target Scoring

Lower score wins:

```text
score = distance * 0.5 + target_energy * 1.7 + target_age * 85 - current_target_bonus
```

Circle keeps its current target unless another target is clearly better or the
current target becomes stale.

## Movement Rules

Priority order:

1. Wall escape: drive inward from current or projected wall risk.
2. Separation: move away from close enemy or recent collision.
3. Melee minimum-risk destination.
4. Normal orbit.
5. 1v1 flattener direction flip.

Wall escape and separation both use clear margins so the bot does not chatter
between states near the threshold. Wall escape starts on current or projected
wall risk and uses the shared destination driver toward an interior point on
the threatened axis, so it does not target its current position while trying to
leave the edge. Normal 1v1 orbit uses a wider flattener strafe offset and a
longer direction-switch cooldown so the bot commits to a visible strafe before
changing direction. On detected enemy fire, Circle can briefly tighten or widen
its orbit instead of permanently flipping direction; the feint is disabled near
walls using a wider guard than normal wall escape, during close separation, and
while on cooldown. Separation uses a mirrored point away from the close enemy
plus a lateral offset. This keeps the bot from ramming while preserving lateral
motion.

## Firepower Policy

```text
own energy <= LOW_ENERGY_HOLD:
  p = 0.8 if distance < 180 else 0.6
distance < 170:
  p = 1.8
distance < 420:
  p = 1.0
otherwise:
  p = 0.8
```

Circle holds fire when scans are stale, energy is critical, the target is too
far while energy is low, or gun bearing error is too large.

## Gun Policy

Circle Strafer keeps bot-specific `GunPolicy`, fire, target, radar, and
movement surfaces in `circle_config.py`. Its live gun policy follows the
shared experimental selector shape: `dynamic_cluster` is the primary learning
gun, `traditional_gf` is a situational profile gun, and `linear` is an
early/simple movement fallback. It live-selects `linear`, `traditional_gf`,
and `dynamic_cluster` in 1v1. Melee keeps segmented gun stats and live
`traditional_gf` bearings disabled, so `traditional_gf` candidates can appear
as unavailable in switch diagnostics.
The current policy uses aligned aggressive KNN and Traditional GF gates with
the shared trait-based selector priors. Primary KNN can leave fallback linear
early, situational profile guns need a larger margin over KNN unless KNN is in
a low-score slump with trusted source/context evidence, and global-source
situational trials are not retained. Every gun wired by the standard runtime
can be pinned for isolated experiments:

```sh
ROBOCODE_CIRCLE_GUN_MODE=anti_surfer scripts/run-battle.sh --rounds 8 bots/circle-strafer bots/sweep-pressure
```

Valid pinned values are `head_on`, `linear`, `linear_wall_aware`,
`displacement`, `traditional_gf`, `dynamic_cluster`, and `anti_surfer`.

For neutral gun-evaluation telemetry, set:

```sh
ROBOCODE_CIRCLE_GUN_EVAL=1 scripts/run-battle.sh --telemetry --rounds 12 bots/circle-strafer bots/sweep-pressure
```

Use `ROBOCODE_CIRCLE_GUN_EVAL_INTERVAL=1` only for denser diagnostic runs where
extra telemetry volume is acceptable.

## Key Telemetry

- `wall.avoid`: wall escape.
- `separate`: close enemy or collision escape.
- `movement.feint`: enemy-fire timed orbit-radius feint.
- `movement.minimum_risk`: melee destination.
- `movement.flatten`: orbit direction changes.
- `gun.switch_decision`: sampled virtual-gun candidate scores and rejection
  reasons.
- `gun.eval_wave_visit`: optional neutral gun-evaluation result when
  `ROBOCODE_CIRCLE_GUN_EVAL=1`.
- `track`: target, radar, aim mode, fire hold reason.

Use [Tooling: Telemetry Viewer](../../docs/tooling.md#telemetry-viewer) for
launch, reset, audit, and stop commands.

## Tuning Checklist

- Wall clipping or wall twitching: inspect `wall.avoid`, `WALL_MARGIN`,
  `WALL_CLEAR_MARGIN`, `WALL_ESCAPE_DESTINATION_MARGIN`,
  `WALL_LOOKAHEAD_TICKS`, `WALL_ESCAPE_TURNS`, `WALL_ESCAPE_TURN_LIMIT`.
- Close combat losses: inspect `separate`, `SEPARATION_DISTANCE`,
  `SEPARATION_CLEAR_DISTANCE`, `PANIC_DISTANCE`.
- Predictable orbit or excess direction flips: inspect `movement.flatten`,
  `movement.profile_visit`, `FLATTENER_SWITCH_MARGIN`, and
  `FLATTENER_SWITCH_COOLDOWN`. If wall contact clusters around feints, inspect
  `movement.feint` and `FEINT_WALL_MARGIN`.
- Low damage: inspect `hold_reason`, `firepower`, and `aim_mode`.
