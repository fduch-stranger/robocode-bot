# Robocode Bot Test Workspace

This workspace contains two basic Robocode Tank Royale Python bots:

- `bots/test-bot-1`: sweeping pressure bot
- `bots/test-bot-2`: evasive circle-strafer bot

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

The battle runner starts an embedded Robocode Tank Royale server, boots both bot
directories, runs a three-round `1v1` battle, and prints the results.
