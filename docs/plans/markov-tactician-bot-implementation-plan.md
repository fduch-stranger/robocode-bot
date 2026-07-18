# Markov Tactician Bot Implementation Plan

This plan describes a new bot variant built around a battle-persistent
MDL-bounded predictive Markov tactical automaton.

The bot should reuse the existing shared execution systems:

```text
radar lock
target cache
virtual guns
gun waves
movement waves
go-to surfing
potential-field fallback
minimum-risk melee movement
fire gate
telemetry
```

The new behavior belongs in the tactical decision layer. The automaton should
choose among trusted movement, gun, and firepower variants. It must not replace
low-level physics, aiming math, radar control, or emergency safety rules.

## Name And Scope

Working bot name:

```text
markov-tactician
```

Package path:

```text
bots/markov-tactician/
```

Shared tactical support should live under:

```text
bots/bot_core/tactics/
```

The bot is a new experimental variant, not an Adaptive Prime retune. It can
start by copying Adaptive Prime's high-level wiring and policies, then replacing
the fixed tactical decisions with automaton-selected variants.

## Core Principle

The automaton learns predictive tactical states:

```text
state = compressed combat situation that predicts similar future outcomes
```

It should not create a new state just because an observation looks different.
It should create, split, merge, or prune states only when doing so improves
prediction enough to justify the added complexity.

The practical rule:

```text
accept complexity only when it improves outcome prediction after MDL penalty
```

## Lifecycle

The automaton state should survive across rounds within the same battle/game.

Round-scoped data:

```text
active wave snapshots
active bullet snapshots
pending action-credit windows
current state id
recent event ring buffers
transient episode state
```

Battle-scoped data:

```text
tactical states
state prototypes
transition statistics
movement action rewards
gun action rewards
firepower action rewards
split/merge/prune history
calibration and prediction accuracy summaries
```

Clear policy:

```text
on round start:
  keep learned states and action statistics
  clear unresolved transient windows from prior round

on round end:
  finalize or ignore unresolved pending rewards
  keep learned states

on new game / opponent composition change:
  clear learned states, or namespace them by opponent identity
```

This mirrors the existing split between round-scoped waves/history and
battle-scoped learning in shared gun and movement systems.

## Architecture

```text
Robocode events
  -> shared sensors and wave systems
  -> CombatVectorEncoder
  -> TacticalEventExtractor
  -> MdlMarkovAutomaton
  -> TacticalActionSelector
  -> existing movement/gun/firepower execution
  -> RewardAttributionLedger
  -> automaton statistics update
  -> telemetry
```

The first implementation should keep the automaton behind modes:

```text
passive
movement_only
gun_shadow
gun_control
firepower_shadow
firepower_control
full_control
```

Default should be `passive` until telemetry proves useful predictive states.

## Shared Module Layout

Suggested files:

```text
bots/bot_core/tactics/__init__.py
bots/bot_core/tactics/config.py
bots/bot_core/tactics/events.py
bots/bot_core/tactics/features.py
bots/bot_core/tactics/models.py
bots/bot_core/tactics/automaton.py
bots/bot_core/tactics/mdl.py
bots/bot_core/tactics/rewards.py
bots/bot_core/tactics/telemetry.py
```

Suggested bot files:

```text
bots/markov-tactician/README.md
bots/markov-tactician/markov-tactician.py
bots/markov-tactician/markov_config.py
bots/markov-tactician/manifest.json
```

## Combat Vector

Each tactical tick should produce a compact combat vector. It should use
bucketed or normalized values, not raw coordinates.

Initial fields:

```text
battle_mode                 # duel, melee
distance_bucket             # near, mid, far
enemy_lateral_bucket        # fast_left, slow_left, stopped, slow_right, fast_right
enemy_advancing_bucket      # retreating, neutral, advancing
enemy_accel_bucket          # decel, stable, accel
enemy_wall_bucket           # open, near_wall, constrained
own_wall_bucket             # open, near_wall, constrained
own_lateral_bucket          # same shape as enemy lateral
energy_bucket               # losing, even, winning
own_energy_bucket           # low, medium, high
enemy_energy_bucket         # low, medium, high
enemy_fire_readiness        # cold, warm, likely_ready
enemy_recent_fire           # no, yes
incoming_wave_bucket        # none, far, medium, imminent
surf_danger_bucket          # low, medium, high
gun_confidence_bucket       # low, medium, high
selected_gun_family         # linear, knn, profile, fallback
recent_damage_trade_bucket  # losing, neutral, winning
target_age_bucket           # fresh, stale
```

Start with 12-18 stable fields. Add fields only if passive telemetry shows they
improve prediction.

## Tactical Events

Events should be symbolic and sparse enough to be meaningful.

Initial event set:

```text
TICK
ENEMY_FIRED_CONFIRMED
ENEMY_FIRED_EXPECTED
WAVE_IMMINENT
WAVE_PASSED_SAFE
HIT_BY_BULLET
BULLET_FIRED
BULLET_HIT_ENEMY
BULLET_MISSED
BULLET_HIT_BULLET
HIT_WALL
NEAR_WALL
ENEMY_REVERSED
ENEMY_STOPPED
RAM_DANGER
GOOD_ENERGY_TRADE
BAD_ENERGY_TRADE
ROUND_STARTED
ROUND_ENDED
```

Do not update all rewards on every event. Events should feed transitions,
prediction accuracy, and only the relevant reward ledger.

## Tactical Actions

Separate action families. Avoid learning one huge cross-product at first.

Movement actions:

```text
SURF_NORMAL
SURF_CONTINUE_BIAS
SURF_REVERSE_BIAS
SURF_WALL_ESCAPE_BIAS
POTENTIAL_FIELD_NORMAL
POTENTIAL_FIELD_OPEN_RANGE
ANTI_RAM
MELEE_MINIMUM_RISK
```

Gun actions:

```text
GUN_SELECTOR_DEFAULT
GUN_LINEAR
GUN_TRADITIONAL_GF
GUN_DYNAMIC_CLUSTER
GUN_DISPLACEMENT
```

Firepower actions:

```text
FIRE_DEFAULT
FIRE_CONSERVE
FIRE_LOW
FIRE_MEDIUM
FIRE_HIGH
FIRE_FINISH
```

The first control phase should use movement actions only. Gun and firepower
actions should be shadow-scored before they control real shots.

## Data Models

Core dataclasses:

```text
CombatVector
TacticalState
PredictionProfile
TransitionStats
ActionStats
AutomatonSnapshot
RewardSnapshot
SplitProposal
MergeProposal
```

`TacticalState` should contain:

```text
state_id
prototype CombatVector
visits
last_visit_turn
outcome_counts
transition_stats by event/action family
movement_action_stats
gun_action_stats
firepower_action_stats
prediction_profile
recent_surprise
created_round
```

`ActionStats` should contain weighted values:

```text
visits
mean_reward
reward_variance
last_updated_turn
ucb_score inputs
real_outcome_counts
```

Use decayed float counts rather than only integer counts so old behavior can
fade.

## State Ingestion

On each tactical update:

```text
1. encode CombatVector
2. find nearest existing state
3. update current transition for the event
4. assign observation to nearest state unless novelty and MDL justify a split
5. update prototype with a small learning rate
6. record prediction surprise for observed events
```

Start with nearest-neighbor over normalized/bucketed fields. A simple weighted
Hamming or mixed numeric distance is enough.

Initial constraints:

```text
max_states = 32
max_transitions = 512
min_visits_before_split = 30
min_visits_before_merge = 20
max_new_states_per_round = 2
state_decay = 0.995
action_decay = 0.997
```

Increase `max_states` only if telemetry shows enough visits per state.

## MDL Split, Merge, And Prune

Use local MDL, not whole-model recomputation.

Local cost:

```text
local_cost =
  state_penalty
  + transition_penalty * transition_count
  + action_penalty * action_stat_count
  + outcome_negative_log_likelihood
  + transition_negative_log_likelihood
  + reward_prediction_error
```

Split candidates should be generated from one feature dimension at a time:

```text
parent q17
candidate split by own_wall_bucket:
  q17/open
  q17/near_wall
```

Accept split only when:

```text
parent visits >= min_visits_before_split
each child would have enough visits
after_cost + min_mdl_gain < before_cost
state capacity available
```

Merge when:

```text
feature distance is small
prediction profile distance is small
best actions are compatible
merged local MDL is not worse beyond tolerance
```

Prune or merge stale states when:

```text
effective visits below threshold
not visited recently
no action statistics with meaningful confidence
state capacity pressure exists
```

Do not prune active state or states with unresolved reward snapshots.

## Reward Attribution

Reward attribution must be split by responsibility. Do not use one global
reward for movement, guns, and firepower.

### Movement Reward

Movement reward should update only movement action stats.

Snapshot key:

```text
enemy_wave_id or movement_wave identity
state_id
movement_action
turn
distance bucket
wave kind
```

Rewards:

```text
wave passed safely       +1.0
hit by enemy bullet      -damage_taken
hit wall                 -2.0
ram danger avoided       +0.3
bad range exposure       -0.2
```

Preferred attribution anchor:

```text
enemy wave -> movement action snapshot -> wave resolved or bullet hit
```

### Gun Reward

Gun reward should update only gun action stats.

Snapshot key:

```text
bullet_id
state_id
gun_action
selected_mode
selected_guess_factor
fire_turn
distance bucket
```

Rewards:

```text
bullet hit enemy         +damage_dealt
bullet missed wall       -0.3 * bullet_power
bullet hit bullet        separate blocked bucket, default neutral
unresolved at round end  ignore
```

Preferred attribution anchor:

```text
confirmed BulletFiredEvent bullet id -> hit/miss callback
```

### Firepower Reward

Firepower reward should update only firepower action stats.

Snapshot key:

```text
bullet_id
state_id
firepower_action
bullet_power
own_energy
enemy_energy
fire_turn
```

Rewards:

```text
hit damage dealt                 +damage_dealt
missed bullet cost               -bullet_power
kill or finish                   bonus
self left below reserve          penalty
good energy trade window         bonus
bad energy trade window          penalty
```

Firepower reward may share the bullet snapshot with gun reward, but it should
update a separate ledger.

### Combined Rewards

Do not start with combined action rewards. Add interaction stats only after the
separate ledgers are stable:

```text
(state, movement_action, gun_action)
(state, gun_action, firepower_action)
```

## Action Selection

Use separate selection per action family:

```text
movement_action = select movement action for state
gun_action = select gun action for state
firepower_action = select firepower action for state
```

Initial selection modes:

```text
passive:
  record default action that existing logic would have used

shadow:
  select an automaton action but execute default

control:
  execute automaton action if safety gates allow it
```

Use UCB-style exploration only inside the active family:

```text
score = mean_reward + exploration_scale * sqrt(log(state_visits) / action_visits)
```

Guardrails:

```text
unvisited action bonus is capped
unsafe actions are unavailable
state must have minimum visits before non-default control
action must beat default by a margin before control
```

## Safety Overrides

Hard safety rules always win:

```text
critical wall escape
imminent high-danger surf wave
anti-ram emergency
fire gate alignment and energy reserve
radar lock/reacquire requirements
```

The automaton can choose tactical variants only after safety filtering.

## Movement Control Phase

The first real control phase should be movement-only.

Implementation approach:

```text
existing movement stack chooses default destination/command
automaton chooses a movement bias
movement layer applies bias when candidate dangers are close
```

Examples:

```text
SURF_REVERSE_BIAS:
  prefer reverse candidate when surf danger is within small margin

SURF_CONTINUE_BIAS:
  prefer current lateral direction when safe enough

SURF_WALL_ESCAPE_BIAS:
  increase wall risk weight or prefer wall-peeling candidate

POTENTIAL_FIELD_OPEN_RANGE:
  increase enemy repulsion / preferred range when no surf wave exists
```

Do not let movement actions override a clearly safer surf destination.

## Gun Control Phase

Gun control should come after selector calibration or at least shadow telemetry.

Initial gun integration:

```text
passive:
  record state and selected existing aim mode

shadow:
  automaton picks a gun family but existing selector controls fire

control:
  set forced candidate only if gun is available and confidence gates pass
```

Preferred first gun action:

```text
GUN_SELECTOR_DEFAULT
```

Other gun actions should be unavailable unless their component reports a valid
aim bearing and sufficient evidence.

## Firepower Control Phase

Firepower control should be conservative.

Initial behavior:

```text
automaton chooses a power scale or policy bucket
existing fire gate and energy reserve still apply
```

Examples:

```text
FIRE_CONSERVE: scale default by 0.75
FIRE_LOW: cap at 1.0
FIRE_MEDIUM: cap at 1.6
FIRE_HIGH: allow default aggressive policy
FIRE_FINISH: only if target energy and hit confidence pass gates
```

Do not let the automaton fire high power from weak aim confidence or low own
energy without explicit gates.

## Telemetry

Add a new event family:

```text
tactics.state
tactics.transition
tactics.action
tactics.reward
tactics.mdl
tactics.split
tactics.merge
tactics.prune
```

Key fields:

```text
state_id
state_visits
event
combat_vector buckets
selected_movement_action
selected_gun_action
selected_firepower_action
executed_action
control_mode
reward_family
reward
outcome
prediction_probability
surprise
mdl_before
mdl_after
split_or_merge_reason
```

Sampling should be configurable. Full telemetry is useful in passive runs but
too expensive for large A/B sweeps.

## Bot Documentation

`bots/markov-tactician/README.md` should document:

```text
bot role and status
automaton lifecycle
control modes
available movement/gun/firepower actions
reward attribution model
telemetry events
environment variables
validation commands
known limitations
```

Root docs should link the bot only after the package exists.

## Environment Flags

Suggested env prefix:

```text
ROBOCODE_MARKOV_
```

Initial flags:

```text
ROBOCODE_MARKOV_TACTICS_MODE=passive
ROBOCODE_MARKOV_MAX_STATES=32
ROBOCODE_MARKOV_MAX_NEW_STATES_PER_ROUND=2
ROBOCODE_MARKOV_MIN_SPLIT_VISITS=30
ROBOCODE_MARKOV_EXPLORATION_SCALE=0.35
ROBOCODE_MARKOV_STATE_DECAY=0.995
ROBOCODE_MARKOV_ACTION_DECAY=0.997
ROBOCODE_MARKOV_TELEMETRY_SAMPLE=1.0
```

Control modes:

```text
passive
movement_shadow
movement_control
gun_shadow
gun_control
firepower_shadow
firepower_control
full_shadow
full_control
```

## Implementation Milestones

### Milestone 1: Passive Skeleton

Deliver:

```text
bot_core.tactics data models
combat vector encoder
tactical event extraction
state assignment without split/merge
passive telemetry
markov-tactician bot package
```

Verification:

```sh
PYTHONPATH=bots .venv/bin/python -m pytest
scripts/package.sh
scripts/run-battle.sh --telemetry --rounds 1 bots/markov-tactician bots/chase-lock
tools/telemetry_audit.py battle-results/runs/<run>/telemetry --require-bot markov-tactician
```

Success criteria:

```text
bot runs
states are created
state visits accumulate
round transitions do not wipe learned states
telemetry is valid
```

### Milestone 2: Reward Ledgers

Deliver:

```text
movement reward snapshots from movement waves
gun reward snapshots from fired bullets
firepower reward snapshots from fired bullets
separate action stats per family
round-end unresolved cleanup
```

Success criteria:

```text
movement rewards update only movement actions
gun rewards update only gun actions
firepower rewards update only firepower actions
unresolved snapshots do not leak across rounds
```

### Milestone 3: MDL Split/Merge/Prune

Deliver:

```text
local MDL scoring
one-dimensional split proposals
merge proposals
prune/merge stale state behavior
state capacity enforcement
telemetry for accepted/rejected changes
```

Success criteria:

```text
state count stays bounded
states survive across rounds
high-surprise broad states split only after enough visits
similar low-value states merge or prune
```

### Milestone 4: Movement Shadow And Control

Deliver:

```text
movement action selection with UCB
movement shadow telemetry
movement bias application behind safety gates
movement_control mode
```

Success criteria:

```text
control mode does not override critical safety choices
movement actions receive meaningful separate rewards
A/B does not show obvious survival regression in smoke runs
```

### Milestone 5: Gun And Firepower Shadow

Deliver:

```text
gun action shadow selection
firepower action shadow selection
reward attribution for both
calibration summaries by state/action
```

Success criteria:

```text
shadow choices can be compared with executed defaults
action confidence correlates with hit/energy outcomes
no live gun/firepower control yet
```

### Milestone 6: Controlled Gun/Firepower Experiments

Deliver:

```text
gun_control behind strict availability and confidence gates
firepower_control behind energy and aim-confidence gates
full_shadow mode
```

Success criteria:

```text
no forced unavailable guns
no high-power low-confidence shots
telemetry can attribute wins/losses by action family
```

## Testing Strategy

Unit tests:

```text
combat vector bucketing
state distance
state assignment
transition updates
reward attribution routing
UCB selection
MDL split acceptance/rejection
merge/prune behavior
round lifecycle
```

Smoke tests:

```text
1-round local battle with telemetry
multi-round battle verifying state persistence
forced passive mode with no behavior changes
movement_control against repo bots
```

A/B tests:

```text
passive vs Adaptive-like baseline for behavior parity
movement_control vs passive/default movement
later gun/firepower shadow correlation before live control
```

## Promotion Bar

Do not judge by one run. Promote each control phase only after:

```text
telemetry audit clean
state count bounded
state visit distribution not too sparse
reward attribution explained by event snapshots
multi-round state persistence verified
A/B smoke against repo bots not clearly worse
targeted ported-surfer runs show a plausible advantage or diagnostic value
```

For movement control, prefer survival and score stability over flashy one-run
wins. For gun and firepower control, require real conversion evidence, not only
virtual score or reward noise.

## Main Risks

State/action explosion:

```text
mitigation: low max states, split visit minimums, action-family separation
```

Bad reward attribution:

```text
mitigation: separate movement/gun/firepower ledgers and explicit snapshots
```

Overriding strong safety logic:

```text
mitigation: hard safety gates and close-danger tie-break use only
```

Telemetry overload:

```text
mitigation: sampling and passive/full-debug modes
```

Learning opponent-specific noise:

```text
mitigation: battle-scoped state, clear on new game/opponent change, decay
```

## Expected First Useful Outcome

The first valuable result is not a stronger bot. It is evidence that the
automaton discovers predictive tactical states that survive across rounds:

```text
state q17 predicts high hit-by-bullet risk near wall
state q23 predicts strong KNN hit conversion at mid distance
state q31 predicts bad high-power energy trade
```

Only after that should the bot use those states to control behavior.
