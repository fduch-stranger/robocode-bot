# Displacement Gun

Mode: `displacement`

The displacement gun predicts the target with rotation-normalized play-it-forward
replay. It finds historical target states that resemble the current state,
replays the following historical movement from the current target position, and
rotates each replay step from the old heading frame into the current heading
frame. It is a lightweight pattern gun that depends on shared target history
rather than owning a private learner.

## Package Contents

- `gun.py`: `DisplacementGun`, the concrete `GunComponent`.
- `config.py`: `DisplacementGunConfig`, including sample count and selector
  policy thresholds.

## Runtime Behavior

`DisplacementGun` reads `TargetHistoryStore` from the runtime context. For a
target, it ranks historical start snapshots by similarity to the current enemy
state: speed, observed lateral speed, observed advancing speed, observed wall
margin, and recent heading change. Absolute heading difference is a small
tie-breaker because replay steps are rotated into the current heading frame.

For each usable candidate, the gun replays subsequent historical movement from
the current enemy position until bullet travel catches the replayed position.
Movement is normalized by heading, so an old forward-left step is replayed as
forward-left relative to the current enemy heading instead of copied as raw
world-space `dx/dy`. The final aim uses density-best relative-bearing
selection: it finds the strongest local cluster of replay bearings and returns a
weighted centroid around that peak instead of taking the median across all
usable replays.

The gun returns `None` until enough usable history exists. That unavailable
state is expected and should be represented through normal switch diagnostics,
not special-case selector code.

## Behavior Flow

```mermaid
flowchart TD
    A["AimContext"] --> B["read TargetHistoryStore"]
    B --> C{"enough target history?"}
    C -- "no" --> D["return unavailable"]
    C -- "yes" --> E["rank similar historical starts"]
    E --> G["replay following movement from current position"]
    G --> H{"enough usable replays?"}
    H -- "no" --> D
    H -- "yes" --> I["choose density-best bearing cluster"]
    I --> J["return absolute bearing"]
```

## Telemetry Notes

Displacement has no private hit learner. It is scored by the shared virtual-gun
wave scorer and appears in `gun.wave_visit`, `gun.switch_decision`, and
`aim_mode` when selected. Its `GunBearing.metadata` and wave diagnostics expose
replay quality signals such as replay count, best candidate score, peak density,
peak share, bearing spread, and distance bucket.

## Validation Notes

The July 2026 forced check against the Python BasicGFSurfer port compared two
independent 12-round Markov-on/off pairs. Across 24 rounds per configuration,
density-only replay improved Adaptive Prime score from 1699 to 1856, PIF hit
rate from 12.0% to 12.7%, and PIF damage per shot from 0.618 to 0.675. Markov
weighting and its experiment surface were removed because their earlier
validation used the converted legacy surfer and did not hold against the port.

A follow-up test isolated the discrete coarse-match bonus that duplicated the
continuous candidate-distance inputs. Across two more independent 12-round
pairs, removing it improved score from 1857 to 1994, PIF hit rate from 11.8% to
12.5%, and PIF damage per shot from 0.680 to 0.720. The bonus and its now-unused
bucket helpers were removed; continuous similarity and heading-change distance
remain.
