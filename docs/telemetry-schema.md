# Telemetry Event Schema

This file is generated from `bots/bot_core/telemetry/schema.py`.
Run `tools/telemetry_schema_docs.py --output docs/telemetry-schema.md` after changing the schema.

The browser viewer and telemetry audit normalize bot-specific fields into a common dashboard contract.

## Canonical Dashboard Fields

- `aim_mode`
- `bullet_id`
- `damage`
- `distance`
- `evading`
- `evasion`
- `gun_mode`
- `mode`
- `movement_mode`
- `power`
- `reason`
- `target`
- `wall_risk`

## Events

### Combat

| Event | Required Fields | Optional Fields | Aliases |
| --- | --- | --- | --- |
| `hit.bot` | - | `target`, `energy`, `rammed`, `distance`, `near_wall`, `wall_risk` | - |
| `hit.bullet` | `owner`, `power`, `damage`, `energy` | `bullet_direction`, `wall_risk`, `near_wall`, `evade_direction`, `move_direction` | - |
| `hit.wall` | - | `evade_direction`, `move_direction`, `center_bearing`, `wall_escape_until` | - |

### Energy

| Event | Required Fields | Optional Fields | Aliases |
| --- | --- | --- | --- |
| `enemy.energy_drop_ignored` | `reason` | `bot_id`, `raw_drop`, `corrected_drop`, `correction`, `scan_gap`, `distance` | `target` from `bot_id` |
| `enemy.fire_detected` | `power`, `distance`, `evasion` | `bot_id`, `raw_drop`, `corrected_drop`, `correction`, `scan_gap`, `bullet_travel_ticks`, `evading`, `evade_direction`, `move_direction`, `evade_until`, `movement_wave`, `predicted_power`, `prediction_confidence`, `prediction_reason`, `prediction_error`, `power_samples`, `power_mae` | `target` from `bot_id` |
| `enemy.gun_heat_wave` | `power`, `distance`, `reason` | `bot_id`, `confidence`, `samples`, `power_mae`, `target_age`, `movement_wave` | `target` from `bot_id` |

### Fire

| Event | Required Fields | Optional Fields | Aliases |
| --- | --- | --- | --- |
| `bullet.fired` | `bullet_id`, `power`, `aim_mode` | `target`, `direction`, `energy`, `gun_waves`, `gun_samples`, `gun_confidence`, `gun_confidence_visits`, `target_age`, `target_x`, `target_y`, `wave`, `shadow_bullets` | - |
| `bullet.hit_bot` | `bullet_id`, `power`, `damage`, `energy` | `victim`, `target`, `aim_mode` | `target` from `victim` |
| `gun.eval_wave_visit` | - | `target`, `guess_factor`, `samples`, `traveled`, `distance`, `selected_gun`, `virtual_scores`, `gun_scores`, `traditional_gf_guess_factor`, `traditional_gf_error`, `traditional_gf_abs_error` | `aim_mode` from `selected_gun`<br>`gun_mode` from `selected_gun` |
| `gun.switch` | `selected` | `target`, `previous`, `scores` | `aim_mode` from `selected`<br>`gun_mode` from `selected` |
| `gun.switch_decision` | `selected` | `target`, `previous`, `changed`, `candidates` | `aim_mode` from `selected`<br>`gun_mode` from `selected` |
| `gun.traditional_gf_profile` | `target` | `aim_mode`, `global_guess_factor`, `global_weight`, `segment_guess_factor`, `segment_weight`, `blend`, `selected_guess_factor`, `source` | - |
| `gun.wave_visit` | - | `target`, `guess_factor`, `samples`, `traveled`, `distance`, `selected_gun`, `virtual_scores`, `gun_scores`, `traditional_gf_guess_factor`, `traditional_gf_error`, `traditional_gf_abs_error` | `aim_mode` from `selected_gun`<br>`gun_mode` from `selected_gun` |
| `track` | `target`, `distance`, `gun_bearing`, `aim_mode` | `age`, `radar_bearing`, `radar_turn`, `radar_mode`, `radar_target`, `radar_age`, `predicted_x`, `predicted_y`, `aim_guess_factor`, `traditional_gf_global`, `traditional_gf_global_weight`, `traditional_gf_segment`, `traditional_gf_segment_weight`, `traditional_gf_blend`, `traditional_gf_selected`, `traditional_gf_source`, `gun_samples`, `gun_scores`, `firepower`, `hold_reason`, `fire_alignment_limit`, `movement_mode`, `known_targets` | `power` from `firepower`<br>`reason` from `hold_reason` |

### Lifecycle

| Event | Required Fields | Optional Fields | Aliases |
| --- | --- | --- | --- |
| `round.reset` | - | `previous_turn`, `current_turn` | - |
| `telemetry.dropped` | `count` | - | - |
| `telemetry.session` | - | - | - |

### Movement

| Event | Required Fields | Optional Fields | Aliases |
| --- | --- | --- | --- |
| `movement.duel_flatten` | - | `target`, `suggested_direction`, `distance` | - |
| `movement.duel_potential` | - | `target`, `destination_x`, `destination_y`, `force_x`, `force_y`, `distance`, `mode`, `evading`, `turn`, `speed` | `movement_mode` from `mode` |
| `movement.flatten` | - | `target`, `current_direction`, `suggested_direction`, `bucket`, `current_count`, `alternative_count`, `distance`, `reason` | - |
| `movement.flatten_shadow` | - | `target`, `current_direction`, `suggested_direction`, `bucket`, `current_count`, `alternative_count`, `distance`, `reason` | - |
| `movement.goto_surf` | - | `target`, `destination_x`, `destination_y`, `danger`, `wave_kind`, `turn`, `speed` | `movement_mode` from `mode` |
| `movement.minimum_risk` | - | `target`, `destination_x`, `destination_y`, `risk`, `candidates`, `nearest_enemy`, `nearest_enemy_distance`, `reused_destination`, `destination_age`, `turn`, `speed`, `known_targets`, `fire_threat` | `movement_mode` from `mode` |
| `movement.profile_visit` | - | `target`, `guess_factor`, `bin`, `bucket`, `visits`, `wave_age`, `ensemble_danger`, `ensemble_samples` | - |
| `search.wall_avoid` | - | `x`, `y`, `center_bearing`, `evade_direction`, `near_wall` | - |
| `separate` | - | `target`, `distance`, `away_bearing`, `target_speed`, `turn_limit`, `move_direction` | - |
| `wall.avoid` | - | `x`, `y`, `center_bearing`, `move_direction`, `evade_direction`, `target` | - |

### Targeting

| Event | Required Fields | Optional Fields | Aliases |
| --- | --- | --- | --- |
| `scan.new` | - | `bot_id`, `energy`, `x`, `y` | `target` from `bot_id` |
| `scan.reacquired` | - | `bot_id`, `previous_age`, `previous_x`, `previous_y`, `x`, `y` | `target` from `bot_id` |
| `search` | - | `known_targets` | - |
| `target.dead` | - | `bot_id` | `target` from `bot_id` |
| `target.drop_lost` | - | `bot_id`, `age`, `cached_x`, `cached_y`, `cached_distance`, `known_targets` | `target` from `bot_id` |
| `target.reacquire` | - | `target`, `age`, `distance`, `radar_mode` | - |
| `target.select` | `selected` | `previous`, `score`, `fresh_candidates`, `candidate`, `candidate_score`, `previous_age`, `known_targets` | `target` from `selected` |
| `target.stale` | - | `bot_id` | `target` from `bot_id` |
