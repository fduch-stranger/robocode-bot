# BasicGFSurfer Port

Python Tank Royale port of the fixed local `BasicGFSurfer` legacy benchmark.

The bot intentionally keeps the legacy shape instead of using the shared
virtual-gun and movement stacks:

- 47-bin wave-surfing danger profile
- enemy energy-drop surf waves
- fixed-power segmented guess-factor gun
- no-wave orbit fallback
- wall and stationary escape recovery from the fixed legacy variant

Use it as a local, non-legacy surfer benchmark:

```sh
scripts/run-battle.sh --rounds 1 bots/adaptive-prime bots/ports/basic-gf-surfer-port
scripts/run-battle.sh --rounds 24 bots/adaptive-prime bots/ports/basic-gf-surfer-port
```

The legacy Java fixed bot remains available through `--legacy basic-gf-surfer`.
This Python port is useful for checking whether surfer behavior can be made
stable without the legacy bridge, but it is not currently strength-equivalent
to the fixed Java legacy bot.
