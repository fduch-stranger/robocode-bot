# BasicGFSurfer Port

Python Tank Royale port of the fixed local `BasicGFSurfer` legacy benchmark.

The bot intentionally keeps the legacy shape instead of using the shared
virtual-gun and movement stacks:

- 47-bin wave-surfing danger profile
- enemy energy-drop surf waves
- fixed-power segmented guess-factor gun
- staged radar search/lock that leaves recent scan locks intact
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

The launcher script sets the normal repo/package import path. The bot file also
has a small direct-GUI-launch bootstrap so Tank Royale GUI runs that start the
`.py` file directly can still find the repo `.venv` dependency install and
re-exec older Python interpreters through `.venv/bin/python`.

When changing parity behavior, compare against the embedded
`wiki/BasicGFSurferFixed.java` source and generated wrapper from the local fixed
legacy jar setup, not Robowiki source alone. The fixed benchmark also depends on
the Tank Royale `robocode-api-bridge` compatibility layer.

Parity work for this port is tracked in
[BasicGFSurfer Python parity](../../../docs/plans/basic-gf-surfer-python-parity-plan.md).
