# BasicGFSurfer Port

Python Tank Royale port of the fixed local `BasicGFSurfer` reference opponent.

The bot intentionally keeps the legacy shape instead of using the shared
virtual-gun and movement stacks:

- 47-bin wave-surfing danger profile
- enemy energy-drop surf waves
- fixed-power segmented guess-factor gun with explicit once-per-turn wave timing
- staged radar search/lock that leaves recent scan locks intact
- no-wave orbit fallback
- wall and stationary escape recovery from the fixed legacy variant

Use it as the primary local, non-legacy surfer benchmark:

```sh
scripts/run-battle.sh --rounds 1 bots/adaptive-prime bots/ports/basic-gf-surfer-port
scripts/run-battle.sh --rounds 24 bots/adaptive-prime bots/ports/basic-gf-surfer-port
```

The legacy Java fixed bot remains available through `--legacy basic-gf-surfer`.
For current Adaptive combat-economics and gun-selection work, prefer this port
over the legacy Java bot. Ported-surfer runs do not need high-accuracy round
filtering; high Adaptive accuracy against the port is real performance or a
real exploit of this bot.

The launcher script sets the normal repo/package import path. The bot file also
has a small direct-GUI-launch bootstrap so Tank Royale GUI runs that start the
`.py` file directly can still find the repo `.venv` dependency install and
re-exec older Python interpreters through `.venv/bin/python`.

Telemetry remains observation-only for parity. With `--telemetry`, the port
emits `bot.turn_timing` and `bot.skipped_turn` so slow-turn or skipped-tick
investigations can compare it with the shared-stack local bots.

When changing parity behavior, compare against the embedded
`wiki/BasicGFSurferFixed.java` source and generated wrapper from the local fixed
legacy jar setup, not Robowiki source alone. The fixed benchmark also depends on
the Tank Royale `robocode-api-bridge` compatibility layer.

Parity lessons from this port are captured in the
[legacy bot porting guideline](../../../docs/legacy-bot-porting-guideline.md).
