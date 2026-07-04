# Championship Results

Date: 2026-07-04

1v1 Champion: **Adaptive Prime 1.0**

Melee Champion: **Chase Lock 1.0**

## Method

The local championship used only discoverable local bot manifest directories
under `bots/`. Legacy bots were intentionally excluded.

The 1v1 championship used a round-robin between all four local bots. Each pair
ran 3 battle runs of 24 rounds, for 72 rounds per matchup and 216 total 1v1
rounds per bot.

Ranking order uses match wins, then battle-run wins, then total score, first
places, and bullet damage.

## 1v1 Championship

| Rank | Bot | Matches | Runs | Score | 1sts | Survival | Bullet Damage |
| ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | Adaptive Prime | 3-0 | 9-0 | 34155 | 210 | 10500 | 18014 |
| 2 | Sweep Pressure | 2-1 | 6-3 | 28429 | 125 | 6250 | 17921 |
| 3 | Chase Lock | 1-2 | 2-7 | 20354 | 45 | 2250 | 16227 |
| 4 | Circle Strafer | 0-3 | 1-8 | 19253 | 52 | 2600 | 14894 |

## Head-To-Head Results

| Matchup | Winner | Winner Score | Loser Score | Winner 1sts | Loser 1sts |
| --- | --- | ---: | ---: | ---: | ---: |
| Adaptive Prime vs Chase Lock | Adaptive Prime | 12406 | 3193 | 71 | 1 |
| Adaptive Prime vs Circle Strafer | Adaptive Prime | 11681 | 2577 | 72 | 0 |
| Adaptive Prime vs Sweep Pressure | Adaptive Prime | 10068 | 3435 | 67 | 5 |
| Chase Lock vs Circle Strafer | Chase Lock | 10713 | 10452 | 35 | 37 |
| Chase Lock vs Sweep Pressure | Sweep Pressure | 13165 | 6448 | 63 | 9 |
| Circle Strafer vs Sweep Pressure | Sweep Pressure | 11829 | 6224 | 57 | 15 |

## Melee Confirmation

The four local bots were also tested together in a melee series: 3 runs of 24
rounds.

| Rank | Bot | Score | Avg Score | 1sts | Avg Rank |
| ---: | --- | ---: | ---: | ---: | ---: |
| 1 | Chase Lock | 16592 | 5530.667 | 12 | 1.0 |
| 2 | Sweep Pressure | 14491 | 4830.333 | 29 | 2.667 |
| 3 | Circle Strafer | 11716 | 3905.333 | 13 | 3.0 |
| 4 | Adaptive Prime | 11190 | 3730.0 | 18 | 3.333 |

Chase Lock ranked first in all 3 melee runs.

## Artifacts

Generated local-only battle artifacts:

- `battle-results/tournaments/champion-20260704-154446/summary.json`
- `battle-results/series/local-melee-champion-20260704-154446/summary.json`

`battle-results/` is ignored by git, so this document is the tracked summary of
the championship run.

## Notes

- Legacy bots did not participate in this championship.
- Adaptive Prime remains the 1v1 champion, winning every 1v1 battle run.
- Chase Lock is the current local melee champion, winning every melee battle
  run.
