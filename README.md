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

Archives are written to `dist/`.

## Run a Battle

```sh
scripts/run-battle.sh
```

The battle runner starts an embedded Robocode Tank Royale server, boots the bot
directories, runs three rounds, and prints the results. Two bots run as `1v1`;
three or more bots run as `melee`.

With no arguments, the script runs every bot directory found under `bots/`.
Results are also written to `battle-results/latest.json`.

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

Enable bot decision logs:

```sh
scripts/run-battle.sh --debug bots/chase-lock bots/circle-strafer
```

Debug logs are written under `battle-results/debug/`.
All current bots write debug logs when `--debug` is enabled.
