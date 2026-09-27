# Jev Advisor Bot Plan

**Status (2026-09-27): removed.** Neither phase passed its gate (see Results).
The code this page describes is in commit `e388ecf` (PR #8) if a later
experiment needs it.

This plan describes an experimental bot variant, `adaptive-jev`, that adds
TypeSafe AI's Jev model as an asynchronous advisor on top of Adaptive Prime.
Jev never aims or steers directly. It answers typed questions, and Adaptive
Prime's existing numeric systems act on those answers when they arrive.

The experiment is opt-in and depends on the network by design. It must never
make the bot worse when Jev is slow, wrong, or unreachable.

## Goal

Measure whether Jev can improve Adaptive Prime against the BasicGFSurfer port
(the fixed enemy benchmark). When it cannot, stop early and record the result.

Non-goals:

- Replacing aim, KNN guns, or go-to surfing with model output.
- Blocking a turn on a network call.
- Shipping Jev in Adaptive Prime itself or in competition packages.

## What Jev Is

Checked against `docs.typesafe.ai` on 2026-09-27:

- **Endpoint.** `POST https://api.typesafe.ai/v1/systemone` with
  `Authorization: Bearer <key>`. The body holds a `state` (a string, object, or
  array), a `model`, and a map of named `questions`.
- **Questions.** There are three types:
  - `choice`: up to 255 options, each with a description.
  - `score`: 2-10 ordered levels.
  - `noul`: returns the probability that the answer is yes.

  Every question in a request sees the same state and is evaluated on its own,
  so one call can ask several questions.
- **Answers.** A `choice` answer returns the chosen option, a probability for
  each option, and a `confidence`. A `noul` answer returns a value from 0 to 1.
  The response names the versioned model that answered.
- **Model.** `jev-latest` currently resolves to `jev-1.13.0`. Pin the versioned
  ID for A/B runs, so a move of the alias cannot change results mid-experiment.
- **Limits.** 1,200 requests per minute, 250,000 tokens per second, and 64k
  tokens per request. The limits change without notice. A 429 or 529 response
  means back off.
- **Price.** $0.042 per million input tokens. Output is free.
- **Weak spots.** The Jev 1.13 notes list numeric precision, counting and
  arithmetic, and large states full of irrelevant detail. So keep math in code,
  send named buckets instead of raw numbers, and send only what each question
  needs.
- **No per-customer tuning.** Jev is not fine-tuned for individual accounts.
  Domain knowledge goes into the state and into each question's criteria.
- **SDK.** The Python SDK (`typesafe-sdk`) reads `TYPESAFE_API_KEY`. It also
  adds a dependency, a 10 s default timeout, and automatic retries, so the bot
  calls the HTTP API with the standard library instead (see Architecture).

## Expected Value

Adaptive Prime's defaults were tuned against this surfer. An opponent-style
answer of "surfer" can therefore only confirm the defaults. Phase 1 cannot raise
the surfer benchmark on its own; its value would show only against a mixed set
of opponents.

The surfer score can move only through per-wave or per-shot decisions (Phases 2
and 3). Those decisions compete with learned statistics that Jev never sees in
full. The prior chance of a gain is low, so every phase runs in shadow mode
first and is dropped when it fails its shadow gate.

## Core Constraints

- **Turn budget.** Every Tank Royale 1.3.1 preset allows 30 ms per turn, so
  every call is asynchronous.
- **Latency in turns.** This depends on TPS:

  | TPS | Turn rate | 70-500 ms call | 24-round battle (about 21,500 turns) |
  | --- | --- | --- | --- |
  | Unlimited (CLI benchmarks) | About 300 turns per second | About 20-150 turns | About 70 s |
  | 30 | 30 turns per second | 2-15 turns | About 12 minutes |

- **Per-wave answers.** Enemy bullets take roughly 20-40 turns to arrive, so
  per-wave answers are usable in active mode only at a low fixed TPS. Shadow
  accuracy does not depend on latency, so it can be measured at any TPS.
- **Request rate.** The surfer fires about 1,300 waves per battle, about 18 per
  second at unlimited TPS. That is close to the account's request limit. The
  client caps requests at 10 per second, so shadow runs at unlimited TPS sample
  about half the waves.
- **Determinism.** With Jev enabled, battles cannot be reproduced exactly, so
  A/B results need the usual repeats.

## Architecture

```text
bots/adaptive-jev/
  adaptive-jev.py        # thin subclass of Adaptive Prime; wires the advisor
  adaptive-jev.json/.sh  # bot metadata and launcher
  jev_config.py          # tuning and flags for the Jev layer
  README.md
bots/bot_core/advisors/
  __init__.py
  client.py              # AdvisorClient: worker thread, bounded queue, answer cache
  jev_transport.py       # HTTP POST with urllib; key read from the environment
  stub_transport.py      # offline fixed or random answers
  schemas.py             # question builders and answer parsing
  state_summary.py       # game state -> named buckets
```

- **Subclass.** `adaptive-jev` subclasses Adaptive Prime and overrides only the
  hook points. Adaptive Prime stays unchanged and remains the A/B baseline.
- **Non-blocking submit.** `AdvisorClient.submit()` never blocks. The client has
  one daemon worker thread, a bounded queue that drops the oldest request, and a
  client-side rate limit. Answers go into a cache along with the turn each was
  requested and the turn it arrived.
- **Reading answers.** During its turn the bot reads answers only from the
  cache. It ignores an answer that is older than the question's
  `max_age_turns`, that belongs to a wave that has already passed, or whose
  confidence is below the threshold.
- **Fallback.** Any of these gives "no answer", which falls through to exact
  Adaptive Prime behavior: an exception, a timeout, an HTTP error, a missing
  key, or the disabled flag. A 429 or 529 pauses the worker briefly. Requests
  are never retried within their age limit.
- **Named buckets.** State summaries use buckets computed in code, never raw
  coordinates. Examples: "lateral speed: fast", "reverses soon after our shots:
  often".

## Decisions

### Phase 1: Opponent Style (Shadow Only)

**Question.** A `choice` asked once per round and then every 200 turns:
classify the enemy's movement and fire style from a bucketed battle summary.
The summary covers:

- lateral speed and reversal rate;
- reversal timing relative to our shots;
- preferred distance and its trend;
- share of time near walls, and ram attempts;
- enemy fire power and hit rate.

**Options.** Wave surfer, orbiter, chaser, sweeper, oscillator, linear mover,
random mover, stationary. The question is asked only after 120 scans, so there
is no "unknown" option.

**Gate.** Jev's accuracy must beat a rule-based classifier in code that uses the
same buckets. It is measured against four opponents: the surfer port, Chase
Lock, Circle Strafer, and Sweep Pressure, with each label taken from that bot's
README.

Active style routing needs per-style profiles, and those do not exist yet. So
even if the gate passes, active routing stays out of scope for this experiment;
a pass is recorded as groundwork for a later mixed-opponent experiment.

### Phase 2: Wave Surf Side (Per Enemy Wave)

**Question.** A `choice` asked when an enemy wave is detected: should we move
forward, reverse, or stop?

**Input.** The wave's bucketed features (distance, our lateral direction and
speed, wall room ahead and behind), plus where the enemy's recent bullets passed
us, as guess-factor buckets.

**Action in active mode.** Multiply the danger of go-to candidates on the
disfavored side by a configured factor (for example 1.15). Discard an answer
that arrives later than `max_age_turns` or after the wave has passed.

**Gate.** Bots never see enemy bullets that miss, so the hit rate of the side
Jev favored cannot be measured for waves we dodged. The gate is therefore an
information test: over at least 1,000 answered waves in shadow mode against the
surfer, waves where Jev's choice differed from where we actually went must be
hit more often than waves where it matched (one-sided two-proportion z-test,
z >= 1.96). If Jev's choice carries no information about the enemy's aim,
following it cannot help. Only when the gate passes:

1. add `--tps` tooling;
2. run the active A/B at a low fixed TPS (30, unless the latency profile allows
   higher), against a baseline run at the same TPS.

### Phase 3 (Optional): Firepower

Only if Phase 2 passes. The question is whether to fire at low, medium, or high
power for the next shot, given bucketed energy, distance, and hit rates. It uses
the same shadow gate, and answers only bias the existing choice.

## Environment Flags

Set flags in `.env` for GUI battles. A/B runs pass them explicitly on both
sides, because inherited values override `.env`.

| Flag | Default | Purpose |
| --- | --- | --- |
| `TYPESAFE_API_KEY` | unset | Secret; set only in `.env`. Never committed, logged, or passed on a command line. |
| `TYPESAFE_BASE_URL` | `https://api.typesafe.ai` | API base URL. |
| `ROBOCODE_JEV_ENABLED` | `0` | Master switch; `0` means exact Adaptive Prime behavior. |
| `ROBOCODE_JEV_MODE` | `shadow` | `shadow` asks and logs; `active` applies answers. |
| `ROBOCODE_JEV_PHASES` | `style` | Comma list: `style`, `surf`, `power`. |
| `ROBOCODE_JEV_TRANSPORT` | `jev` | `jev` or `stub`. |
| `ROBOCODE_JEV_MODEL` | `jev-1.13.0` | Model ID; pinned for A/B runs. |
| `ROBOCODE_JEV_TIMEOUT_MS` | `1500` | Per-request timeout. |
| `ROBOCODE_JEV_MAX_INFLIGHT` | `2` | Queue bound; the oldest request is dropped. |
| `ROBOCODE_JEV_MAX_RPS` | `10` | Client-side request rate limit. |
| `ROBOCODE_JEV_WORKERS` | `2` | Worker threads (parallel requests). |

The [bot README](../../bots/adaptive-jev/README.md) lists the stub flags.

## Secret Handling

- **How the key reaches the bot.** The bot launchers source `.env`, so a key
  there reaches `adaptive-jev` in both GUI and CLI battles. For A/B runs from a
  git worktree, set `ROBOCODE_ENV_FILE` to the main checkout's `.env` rather
  than copying the file.
- **Where it is read.** Only `jev_transport.py` reads the key.
- **Where it never goes.** The key is kept out of:
  - `bot.config`, telemetry, debug logs, and exception messages;
  - A/B manifests (it is never passed through `--candidate-env`);
  - `dist/` (`scripts/package.sh` skips `adaptive-jev`).
- **Test.** A unit test sets a fake key and asserts that it appears in no
  telemetry record or log line.

## Telemetry

New events, added to `docs/telemetry-schema.md` when implemented:

- `advisor.request`: question kind, request turn, and state size in characters.
- `advisor.answer`: question kind, latency in ms and in turns, model ID, answer,
  probabilities, and confidence. It also records whether the answer was applied,
  stale, below the confidence threshold, or shadow-only.
- `advisor.error`: question kind and error class (timeout, HTTP status, or
  parse). It never includes the response body.
- `advisor.outcome` (Phase 2): for each answered wave, the side Jev favored,
  where we ended up (`forward`, `reverse`, or `stop`, from the visit guess
  factor), and whether the wave hit us.
- `bot.config` gains the advisor flags and the transport name.

`tools/advisor_summary.py` reports latency percentiles, stale and error rates,
and shadow accuracy for each phase. Active A/B runs keep telemetry off; latency
and stale rates come from the shadow runs.

## Milestones

Each milestone ends by recording its result in the Results table.

0. **API probe.** `tools/jev_probe.py` sends about 30 requests shaped like the
   Phase 1 and Phase 2 questions. It reports latency percentiles, errors, and
   the model ID. If the key or the endpoint fails, stop the experiment.
1. **Skeleton.** Build the following, then merge via PR:
   - `bots/adaptive-jev`, the advisor client, both transports, the flags, the
     telemetry events, and the summary tool;
   - unit tests for non-blocking submit, stale drop, error fallback, rate
     limiting, and secret redaction;
   - the package exclusion;
   - CLI smoke battles, one with the stub transport and one with Jev in shadow
     mode.

   With `ROBOCODE_JEV_ENABLED=0`, the advisor is never constructed and every
   hook defers to Adaptive Prime; this is unit-tested.
2. **Phase 1 shadow.** Run short battles against each local opponent and
   compare accuracy with the rule-based classifier.
3. **Phase 2 shadow.** Run 24 x 3 against the surfer port in shadow mode. Report
   the latency profile, and compare Jev's side accuracy with our surfing choice.
4. **Phase 2 active A/B** (only if its gate passed).
   - Add `--tps` to `run-battle.sh` and the runner.
   - Add a preset that runs `adaptive-jev` with `ROBOCODE_JEV_ENABLED=0` and
     with `=1` against the surfer port at the chosen TPS.
   - Give the candidate 6 runs, against a baseline run at the same TPS.
   - Merge only on a win.
5. **Decision.** Keep `adaptive-jev` as an experimental bot or remove it. Then
   update this plan, the roadmap, and the project memories.

## Results

| Milestone | Result |
| --- | --- |
| 0. API probe | Pass. 70/70 requests OK on `jev-1.13.0`. Sequential: p50 287 ms, p90 383 ms, max 410 ms. Four in parallel: p50 252 ms, about 15 requests per second. About 616 input tokens per request. On idealized feature profiles Jev named the intended style 31 of 35 times (it read the oscillator as an orbiter); the rule-based classifier's order was fixed before any battle so that it classifies all 8 prototypes. |
| 1. Skeleton | Done (PR #8). `bots/adaptive-jev`, `bot_core/advisors`, advisor telemetry, and `tools/advisor_summary.py`; 355 tests pass. Disabled mode runs Adaptive Prime's class itself (6-round sanity check: Adaptive Prime 5 first places, disabled Adaptive Jev 4). Live shadow smoke: 0 errors, p50 256 ms, about 145 turns at unlimited TPS. |
| 2. Phase 1 shadow | Gate passed narrowly; no active step follows. Across 8-round battles against each opponent (116 answers), Jev was right 0/30 times on the surfer (28 answers were "orbiter"), 11/32 on Circle Strafer, 5/17 on Chase Lock, and 5/37 on Sweep Pressure. That is 19% mean accuracy, against 3% for the rule-based classifier and 12.5% for chance. The logged summaries show why: the surfer's reversals are not tied to our wave passes, so both classifiers see it as an orbiter. Active style routing stays out of scope, because it needs per-style profiles and cannot raise the surfer benchmark. |
| 3. Phase 2 shadow | Gate failed. Planned sample (24 x 3, 2,732 answered waves): stratified z = 0.67. Fresh confirmation sample (24 x 3, 2,684 waves): z = 0.36. The first, unstratified version of the test passed (z = 4.7) only because Jev never answers stop, and waves where we stayed near guess factor 0 are hit 16-17% of the time against 4-10% otherwise; the gate now compares within each outcome. Two runs made for a performance check reached z = 2.31 and all eight runs pooled reach z = 2.13, but those were not the planned test. An effect of that size (about 2 points of hit rate on the comparable waves) would change damage taken by only a few percent, below what a 6-run A/B detects. Latency: p50 255 ms, about 107 turns at unlimited TPS, and 8% of answers arrived before the wave passed. 0 errors in 7,337 answers, about 550 input tokens each. |
| 4. Phase 2 active A/B | Skipped: Phase 2 failed its gate, so the `--tps` tooling and the 30 TPS A/B were not built or run. |
| 5. Decision | Removed `bots/adaptive-jev`, `bot_core/advisors`, the advisor telemetry, and both tools. Neither phase showed a usable signal. Live shadow runs also scored 1480 on average (8 runs, range 1079-1878) against 1699 for Adaptive Prime and stub-transport controls (5 runs, 1588-1769). Three live runs collapsed below 1210 with no timing signature (1-3 skipped turns); that gap is unexplained and was not investigated further. |

## Risks

- **Latency makes answers useless.** Mitigated by a maximum age per phase,
  shadow runs first, and a low fixed TPS for per-wave decisions.
- **Zero-shot answers are noisy.** Jev does not learn this opponent during the
  battle. Promote a phase only on shadow evidence.
- **Network flakiness biases results.** Error and stale rates are logged, and
  the fallback is exact Adaptive Prime behavior.
- **Rate limits change without notice.** The client limits its own request rate,
  backs off on 429 and 529, and logs throttling.
- **Key leakage.** See Secret Handling.
- **Cost.** About 500 input tokens per request. A 24-round battle with a
  question on every sampled wave uses under a million tokens, which is a few
  cents at published pricing.
