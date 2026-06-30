# Robocode Bot Test Workspace

This workspace contains two basic Robocode Tank Royale Python bots:

- `bots/sweep-pressure`: aggressive sweeping pressure bot
- `bots/circle-strafer`: evasive circle-strafer bot
- `bots/chase-lock`: radar/gun target-locking chase bot

## Setup

```sh
scripts/setup.sh
```

## Package Bots

```sh
scripts/package.sh
```

Archives are written to `dist/`. Each archive includes the bot directory plus
the shared `bot_utils` helper package used by the Python bots.

## Run a Battle

```sh
scripts/run-battle.sh
```

The battle runner starts an embedded Robocode Tank Royale server, boots the bot
directories, runs three rounds, and prints the results. Two bots run as `1v1`;
three or more bots run as `melee`.

With no arguments, the script runs every bot directory found under `bots/` that
contains a bot JSON manifest. Helper packages such as `bot_utils` are ignored.
Each run writes artifacts under `battle-results/runs/<timestamp>/`:

- `results.json`: structured final scores
- `runner.log`: runner lifecycle, round, boot, and optional tick-sample events
- `process.log`: raw Robocode runner, server, and booter output
- `debug/`: bot decision logs when `--debug` is enabled
- `recordings/game-*.battle.gz`: battle recording when `--record` is enabled
- `intents.jsonl`: captured bot intents when `--intent-diagnostics` is enabled

You can pass explicit bot directories to test a different pairing:

```sh
scripts/run-battle.sh bots/chase-lock bots/circle-strafer
```

Or pass three or more bot directories for a melee battle:

```sh
scripts/run-battle.sh bots/chase-lock bots/sweep-pressure bots/circle-strafer
```

Use more rounds for less noisy comparisons:

```sh
scripts/run-battle.sh --rounds 30
```

Write structured results to a specific file:

```sh
scripts/run-battle.sh --rounds 30 --results battle-results/chase-vs-circle.json bots/chase-lock bots/circle-strafer
```

Use a stable run directory for all artifacts:

```sh
scripts/run-battle.sh --run-dir battle-results/runs/manual-1
```

Enable bot decision logs:

```sh
scripts/run-battle.sh --debug bots/chase-lock bots/circle-strafer
```

Debug logs are written under the run directory by default.
All current bots write debug logs when `--debug` is enabled.

Enable runner-side battle recording, intent diagnostics, and sampled tick logs:

```sh
scripts/run-battle.sh --record --intent-diagnostics --tick-sample 25
```
