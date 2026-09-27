# Adaptive Prime

Adaptive Prime is the 1v1 champion candidate. It uses the full shared stack:
virtual guns, enemy-fire detection, go-to surfing, movement learning,
minimum-risk melee movement, and telemetry.

Shared references:

- [Shared Bot Systems](../../docs/bot-shared-systems.md)
- [Bot Core Data Structures](../../docs/bot-core-data-structures.md)
- [Tooling](../../docs/tooling.md)

Bot-specific tuning lives in policy dataclasses in `adaptive_config.py`:
`GunPolicy`, `TraditionalGfPolicy`, `FirePolicy`, `DuelFirepowerPolicy`,
`MeleeFirepowerPolicy`, `TargetPolicy`, `RadarPolicy`, `MovementPolicy`, and
`DuelMovementPolicy`. Effective shared-system overrides are also centralized
there as `MOVEMENT_FLATTENING_CONFIG` and `MINIMUM_RISK_CONFIG`; behavior code
should not carry independent tuning literals.

## Behavior

```mermaid
flowchart TD
    A["scan or tick"] --> B["select target"]
    B --> C["update gun and movement waves"]
    C --> D["aim with virtual gun system"]
    D --> E["lock or reacquire radar"]
    E --> F{"battle mode"}
    F -- "1v1" --> G{"surfable wave?"}
    G -- "yes" --> H["option surf: orbit either way or stop"]
    G -- "no" --> I["potential-field route"]
    F -- "melee" --> J["minimum-risk route"]
    H --> K["fire gate"]
    I --> K
    J --> K
```

Adaptive is different from the other local bots in three places:

- It surfs enemy waves by choosing between orbiting either way and stopping,
  looking one wave ahead, when an enemy wave is usable.
- It falls back to potential-field routing in 1v1 instead of simple orbiting.
- It raises firepower more aggressively when gun confidence and energy position
  are good.

## Movement

1v1 movement priority:

1. Use shared option surfing when an enemy wave is in flight: simulate
   orbiting clockwise, orbiting counter-clockwise and stopping until the wave
   passes, integrate the learned danger over the exact guess-factor span the
   bot covers while the bullet ring breaks on it, add the cheapest
   continuation against the next wave, and drive the safest option. Stops are
   real stops: the engine brakes to zero in one turn. The orbit leans toward
   the duel policy's preferred distance. `ROBOCODE_ADAPTIVE_OPTION_SURFING=0`
   restores the older go-to surfing. Promoted in PR #19: 6 runs against the
   BasicGFSurfer port scored 2021 ± 98 versus the 18-run pooled baseline of
   1740 ± 44 (+16%, z 2.6), with bullet damage dealt +26% and damage taken
   unchanged.
2. Otherwise use shared go-to surfing when a wave can be scored.
3. Otherwise compute a potential-field destination from enemy repulsion,
   orbit tangent, fire-threat repulsion, wall repulsion, and center attraction.
4. Use distance bands to panic-open, open range, orbit, or reconnect. The
   duel policy prefers 480 px and holds at least 380 px; it used to prefer
   580 px, where every gun hit about 13% against the BasicGFSurfer port.

Melee uses shared minimum-risk movement. In `track` telemetry this appears as
`movement_mode=melee_minimum_risk`.

Key movement telemetry:

- `movement.option_surf`
- `movement.goto_surf`
- `movement.duel_potential`
- `movement.minimum_risk`
- `enemy.fire_detected`
- `enemy.gun_heat_wave`

## Guns

Normal selectable guns are `linear`, `dynamic_cluster`, `traditional_gf`, and
`displacement`.

Selector roles:

| Gun | Role |
| --- | --- |
| `dynamic_cluster` | Primary learning gun. |
| `displacement` | Situational history-replay gun. |
| `traditional_gf` | Situational profile gun with source-aware gates and a flight/lateral/wall-margin profile. |
| `linear` | Early/simple-motion fallback. |

Adaptive keeps bot-specific selector gates around the shared selector:

- KNN can warm up earlier than in shared defaults.
- Gun changes require a `0.08` score margin to limit context-driven oscillation.
- A fallback needs a `0.18` score margin to replace an active primary gun.
- Trusted Traditional GF segment sources can challenge early.
- Global or weak blended Traditional GF sources are penalized more heavily.
- Situational guns need context/source evidence or a KNN slump to displace KNN.
- Eval waves can add capped selector-only evidence without training production
  learners.

Hot-gun tracking: the full virtual-gun aim and the Dynamic Cluster power
re-aim run only from `full_aim_lead_turns` (3) turns before the gun can fire.
While the gun is hotter than that, the gun follows the last full solution's
offset from the direct bearing, which removes most of the per-turn cost
(`ROBOCODE_ADAPTIVE_HOT_GUN_TRACKING=0` disables it). Gun selection and switch
diagnostics therefore update only on full-aim turns.

Adaptive's default Traditional GF model uses a gun-local key of flight time,
absolute lateral speed, and wall margin. It starts blending a segment after 8
effective visits and reaches full segment weight at 36 visits. The model uses
31 bins, smoothing `1.25`, decay `0.985`, and maximum-bin peak selection. This
configuration beat the former global-only control in all three 24-round Python
BasicGFSurfer repeats (`11.93%` versus `10.39%` hit rate). Superseded
Traditional-GF presets and tuning environment variables are intentionally not
supported. Profile learning still records the full escape range, while firing
is bounded to `|GF| <= 0.87` to exclude the unproductive extreme tail.

For isolated gun testing:

```sh
ROBOCODE_ADAPTIVE_GUN_MODE=displacement \
scripts/run-battle.sh --telemetry --rounds 24 \
  bots/adaptive-prime bots/ports/basic-gf-surfer-port
```

Useful experiment knobs:

```sh
ROBOCODE_ADAPTIVE_GUN_SET=linear,dynamic_cluster,traditional_gf,displacement
ROBOCODE_ADAPTIVE_GUN_EVAL=1
ROBOCODE_ADAPTIVE_GUN_EVAL_INTERVAL=1
ROBOCODE_ADAPTIVE_GOTO_SURFING=0
ROBOCODE_ADAPTIVE_FLATTENER_DIRECTION_CONTROL=0
ROBOCODE_ADAPTIVE_GUN_HEAT_WAVES=0
```

The movement controls disable go-to destination selection and learned
direction application independently. Movement-wave learning remains active so
the controls do not silently change training evidence.

Valid pinned guns are `head_on`, `linear`, `displacement`,
`traditional_gf`, and `dynamic_cluster`.

## Firepower

Adaptive is willing to spend power when close, ahead, or confident:

```text
last stand: up to 0.6 while leaving a small reserve
low energy: 0.6-0.8
finisher: target_energy / 3.5 + 0.2, clamped
close: 1.6-2.2
mid: 1.3-1.8 depending on confidence and energy lead
far: 0.8-1.0
```

The shared fire gate still requires fresh target data, alignment, valid
firepower, and enough energy after the shot. Adaptive uses the shared
`last_stand` path at critical energy instead of a separate KNN-gated low-energy
override, so aligned close shots can still fire below the normal energy margin.

Dynamic Cluster's shot-quality diagnostics can scale the policy firepower down
when it is the selected gun, but that scaling is off by default
(`ROBOCODE_ADAPTIVE_DYNAMIC_SHOT_QUALITY_POWER_SCALING=1` re-enables it).
Against the BasicGFSurfer port the scaling was a constant 0.55x multiplier;
turning it off alone raised bullet damage but lost rounds, and together with
the closer duel distance it is a clear win. See
[Adaptive Prime surfer economics](../../docs/plans/adaptive-surfer-economics.md)
for the measurements.

## Analysis

Primary telemetry:

- `track`: target, radar, aim, movement, fire hold, and selected gun context.
- `gun.switch_decision`: selector candidates, scores, visits, thresholds,
  bonuses, penalties, and rejection reasons.
- `gun.wave_visit`: production virtual-gun scoring.
- `gun.eval_wave_visit`: optional neutral eval-wave scoring.
- `gun.traditional_gf_profile`: Traditional GF source/profile diagnostics.
- `bot.turn_timing` / `bot.skipped_turn`: decision-time budget and skipped tick
  diagnostics.
- `bot.config`: the profile name, deterministic configuration fingerprint, and
  complete effective Adaptive policy/configuration snapshot for experiment
  provenance.

Preferred surfer check:

```sh
scripts/run-battle.sh --telemetry --rounds 24 \
  bots/adaptive-prime bots/ports/basic-gf-surfer-port

tools/telemetry_audit.py battle-results/runs/<run>/telemetry \
  --require-bot adaptive-prime
tools/combat_economics_summary.py battle-results/runs/<run>
tools/gun_eval_summary.py battle-results/runs/<run>/telemetry \
  --bot adaptive-prime --post-switch-shots 6
```

Use [Tooling](../../docs/tooling.md) for the full experiment workflow.
