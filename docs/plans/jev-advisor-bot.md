# Jev Advisor Bot Plan

This plan describes an experimental bot variant, `adaptive-jev`, that adds
TypeSafe AI's Jev "System One" model as an asynchronous advisor on top of
Adaptive Prime. Jev never aims or steers directly. It answers slow-changing,
typed questions (what kind of opponent is this, which way should this wave be
surfed), and Adaptive Prime's existing numeric systems act on those answers
when they arrive.

The experiment is opt-in, network-dependent by design, and must never make the
bot worse when Jev is slow, wrong, or unreachable.

## Goal

Measure whether a fast hosted classifier can improve Adaptive Prime against the
BasicGFSurfer port (the fixed enemy benchmark) by improving high-level
decisions that the per-battle learners adapt to slowly:

```text
opponent style -> gun set, firepower policy, movement profile
enemy wave     -> preferred surf side (bias only)
```

Non-goals:

- Replacing aim, KNN guns, or go-to surfing with model output.
- Blocking a turn on a network call.
- Shipping Jev in Adaptive Prime itself or in competition packages.

## What Jev Is

As published by TypeSafe AI (early access since 2026-09-15; verify against the
current docs before implementing):

- Input: unstructured state (text or structured program state).
- Output: typed, schema-constrained values defined in advance, with calibrated
  probabilities and confidence scores. Enum-style outputs support up to 255
  choices.
- Latency: 70-500 ms end to end.
- Pricing: input tokens only (about $0.042 per million tokens); output is free.
- Access: API key from `console.typesafe.ai`; Python adapter at
  `github.com/typesafe-ai/system-one-adapter-python`; docs at `docs.typesafe.ai`.

Unknowns to resolve in Milestone 0: exact request/response shape, schema
definition format, rate limits, input size limits, whether few-shot examples or
per-application calibration are supported.

## Core Constraints

- Turn budget: every Tank Royale 1.3.1 game preset uses a 30 ms turn timeout.
  A Jev call spans several turns, so every call is asynchronous.
- Latency in turns depends on TPS. At the GUI default of 30 TPS a turn is about
  33 ms of wall time, so 70-500 ms is about 2-15 turns. At unlimited TPS (the
  default for CLI benchmarks) the same call can span 100+ turns. The Jev bot
  must be benchmarked at a fixed TPS (30), and results at other TPS values are
  not comparable.
- Enemy bullets need roughly 20-40 turns to arrive at normal range, so a
  per-wave answer at 30 TPS usually arrives with time to act; at high TPS it
  usually does not and must be discarded.
- Determinism: with Jev enabled, battles are not reproducible. A/B results need
  repeats as usual, plus a shadow-mode control (see Validation).

## Architecture

```text
bots/adaptive-jev/
  adaptive-jev.py        # thin subclass of Adaptive Prime; wires the advisor
  adaptive-jev.json/.sh  # bot metadata and launcher (copied from adaptive-prime)
  jev_config.py          # all tuning and flags for the Jev layer
  README.md
bots/bot_core/advisors/
  __init__.py
  client.py              # transport-agnostic async advisor client
  jev_transport.py       # Jev HTTP/adapter calls, auth from env
  schemas.py             # typed questions and answers
  state_summary.py       # compact state -> advisor input
```

- `adaptive-jev` subclasses Adaptive Prime (loaded via `importlib`, since the
  module file name has a hyphen) and overrides only the hook points below.
  Adaptive Prime stays unchanged, so it remains the A/B baseline.
- `AdvisorClient` owns one daemon worker thread and a bounded queue (drop the
  oldest request when full). `submit(question)` never blocks. Answers land in a
  per-question cache with the turn they were requested and received.
- The bot reads answers only from the cache during its turn. An answer older
  than its question's `max_age_turns`, or for a wave that has already passed, is
  ignored.
- Any exception, timeout, missing key, or disabled flag makes the advisor return
  "no answer", which falls through to exact Adaptive Prime behavior.
- The transport is pluggable, so a local stub (fixed or random answers) can run
  the whole pipeline without network access for tests and shadow baselines.

## Decisions

### Phase 1: Opponent Style (per round and every N turns)

Question: given a compact movement and fire summary of the enemy, classify its
style.

```text
answer: enum {surfer, linear_mover, oscillator, random_mover, rammer, stationary, unknown}
        + probability per class
```

Input summary (state_summary.py), about 20 numbers rendered as short text:
lateral speed mean and variance, reversal rate, distance preference, wall time
share, our hit rate by gun mode, enemy fire power mean, enemy hit rate on us,
damage taken per wave.

Action, only when the top class probability passes a threshold:

- bias the gun selector toward the matching gun set (for example
  `dynamic_cluster` and `traditional_gf` for surfers, `linear` for linear
  movers) by adjusting selector switch margins, never by forcing a mode;
- pick a firepower policy variant from `adaptive_config.py`;
- pick the movement profile weighting.

This is the safest phase: late answers barely matter, and the existing
selector still needs virtual-gun evidence to switch.

### Phase 2: Wave Surf Side (per detected enemy wave)

Question: when an enemy wave is detected, which side should we surf?

```text
answer: enum {clockwise, counter_clockwise, stop} + probabilities
```

Input: the wave features already recorded for `movement.profile_visit`, plus
the enemy's recent hit guess factors against us.

Action: multiply go-to candidate danger on the disfavored side by a configured
factor (for example 1.15). Discard the answer if it arrives later than
`max_age_turns` or after the wave has passed our position.

### Phase 3 (optional): Firepower Per Shot Window

Only if Phase 1 shows value. Question: low, medium, or high power for the next
shots given energy, distance, and recent hit rates. Same bias-only rule.

## Environment Flags

| Flag | Default | Purpose |
| --- | --- | --- |
| `ROBOCODE_JEV_ENABLED` | `0` | Master switch; `0` means exact Adaptive Prime behavior. |
| `ROBOCODE_JEV_MODE` | `shadow` | `shadow` asks and logs but never acts; `active` applies answers. |
| `ROBOCODE_JEV_PHASES` | `style` | Comma list: `style`, `surf`, `power`. |
| `ROBOCODE_JEV_TRANSPORT` | `jev` | `jev` or `stub` (offline, deterministic answers). |
| `TYPESAFE_API_KEY` | unset | Read from `.env` only; never committed, never logged. |
| `ROBOCODE_JEV_TIMEOUT_MS` | `800` | Per-request timeout. |
| `ROBOCODE_JEV_MAX_INFLIGHT` | `2` | Queue bound; oldest request is dropped. |

## Telemetry

New events, added to `docs/telemetry-schema.md` when implemented:

- `advisor.request`: question kind, request turn, input size.
- `advisor.answer`: question kind, latency ms and turns, answer, probabilities,
  and whether it was applied, stale, or discarded.
- `advisor.error`: kind, error class (timeout, HTTP status, parse).
- `bot.config` gains the advisor flags and the transport name.

## Validation

1. **Offline pipeline (stub transport).** Unit tests for the client (never
   blocks, drops stale answers, falls back on errors) and a CLI smoke battle
   with `ROBOCODE_JEV_TRANSPORT=stub`.
2. **Latency profile.** Shadow mode against the surfer at TPS 30; report the
   latency distribution in ms and turns, the stale rate per phase, and the
   error rate.
3. **Shadow accuracy.** In shadow mode, compare Phase 1 answers against known
   opponents (the surfer port, Chase Lock, Circle Strafer, Sweep Pressure, and
   legacy bots) and Phase 2 answers against where the enemy wave actually hit.
   Promote a phase to active only if its shadow accuracy beats a trivial
   baseline (majority class, or current surfing choice).
4. **A/B.** `adaptive-jev` in active mode against Adaptive Prime, both versus
   the surfer port, 24 x 3 at TPS 30, telemetry off apart from advisor events,
   one benchmark at a time (the battle lock enforces this). At TPS 30 a 24-round
   battle takes about 12 minutes, so a full A/B takes about 70 minutes.
5. **Control.** Repeat the A/B with the stub transport returning random
   answers, to confirm that gains come from Jev's answers and not from the bias
   mechanics themselves.

## Tooling Needed

- `run-battle.sh --tps N`, passed to the runner's `BattleSetup`, so Jev
  benchmarks run at a fixed TPS.
- A/B preset `adaptive-jev-1v1-basic-gf-surfer-port` comparing `adaptive-jev`
  with `adaptive-prime` at TPS 30.
- A summary tool (or a `gun_eval_summary` extension) for `advisor.*` events.

## Risks

- **Latency makes answers useless.** Mitigated by per-phase max age, shadow
  measurement first, and Phase 1 being latency tolerant.
- **Zero-shot answers are noisy.** Jev does not learn this opponent during the
  battle the way KNN guns do. Promote only on shadow accuracy evidence.
- **Network flakiness biases results.** Error and stale rates are logged, and
  the fallback is exact Adaptive Prime behavior.
- **Key leakage.** The key is read only from the environment and is excluded
  from `bot.config` and all telemetry.
- **Cost.** About 300 input tokens per request and a few thousand requests per
  battle is well under a cent per battle at published pricing. Recheck before
  long sweeps.

## Milestones

0. **API spike.** Get an early-access key, read the docs, and make one scripted
   request with a Phase 1 schema. Record the real request/response shape and
   latency here.
1. **Skeleton.** `bots/adaptive-jev` subclass, advisor client, stub transport,
   flags, unit tests, and a stub-mode smoke battle. No behavior change while
   `ROBOCODE_JEV_ENABLED=0`.
2. **Tooling.** Add `--tps` to `run-battle.sh` and the runner, plus the A/B
   preset.
3. **Phase 1 shadow.** Opponent-style questions in shadow mode; latency and
   accuracy report.
4. **Phase 1 active A/B.** Promote if shadow accuracy and the A/B both support
   it.
5. **Phase 2 shadow, then active A/B.** Same gate as Phase 1.
6. **Decision.** Keep `adaptive-jev` as an experimental bot, or remove it
   (following the repo practice of removing unproven experiments).
