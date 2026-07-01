# Championship Results

Date: 2026-07-01

Champion: **Adaptive Prime 1.0**

## Method

The local championship used a 1v1 round-robin between all four local bots.
Each pair ran 3 battle runs of 24 rounds, for 72 rounds per matchup and 216
total 1v1 rounds per bot.

Ranking order uses match wins, then battle-run wins, then total score, first
places, and bullet damage.

## 1v1 Championship

| Rank | Bot | Matches | Runs | Score | 1sts | Survival | Bullet Damage |
| ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | Adaptive Prime | 3-0 | 9-0 | 35461 | 214 | 10700 | 18868 |
| 2 | Circle Strafer | 2-1 | 6-3 | 23351 | 100 | 5000 | 14836 |
| 3 | Sweep Pressure | 1-2 | 3-6 | 22362 | 87 | 4350 | 15053 |
| 4 | Chase Lock | 0-3 | 0-9 | 16878 | 31 | 1550 | 13787 |

## Head-To-Head Results

| Matchup | Winner | Winner Score | Loser Score | Winner 1sts | Loser 1sts |
| --- | --- | ---: | ---: | ---: | ---: |
| Adaptive Prime vs Chase Lock | Adaptive Prime | 12600 | 2029 | 72 | 0 |
| Adaptive Prime vs Circle Strafer | Adaptive Prime | 11529 | 1088 | 72 | 0 |
| Adaptive Prime vs Sweep Pressure | Adaptive Prime | 11332 | 1571 | 70 | 2 |
| Chase Lock vs Circle Strafer | Circle Strafer | 12507 | 7427 | 57 | 15 |
| Chase Lock vs Sweep Pressure | Sweep Pressure | 12412 | 7422 | 56 | 16 |
| Circle Strafer vs Sweep Pressure | Circle Strafer | 9756 | 8379 | 43 | 29 |

## Melee Confirmation

The four local bots were also tested together in a melee series: 3 runs of 24
rounds.

| Rank | Bot | Score | Avg Score | 1sts | Avg Rank |
| ---: | --- | ---: | ---: | ---: | ---: |
| 1 | Adaptive Prime | 16467 | 5489.0 | 32 | 1.0 |
| 2 | Circle Strafer | 12402 | 4134.0 | 18 | 2.667 |
| 3 | Sweep Pressure | 12125 | 4041.667 | 16 | 3.0 |
| 4 | Chase Lock | 11549 | 3849.667 | 6 | 3.333 |

Adaptive Prime ranked first in all 3 melee runs.

## Legacy Boss Check

Adaptive Prime was checked against the configured converted legacy
`BasicGFSurfer 1.02` bot for 24 rounds.

| Rank | Bot | Score | 1sts | Avg Rank |
| ---: | --- | ---: | ---: | ---: |
| 1 | Adaptive Prime 1.0 | 2360 | 16 | 1.0 |
| 2 | BasicGFSurfer 1.02 | 1418 | 8 | 2.0 |

## Artifacts

Generated battle artifacts:

- `battle-results/tournaments/champion-20260701-172750/summary.json`
- `battle-results/series/local-melee-champion-20260701/summary.json`
- `battle-results/series/adaptive-vs-basic-gf-surfer-20260701/summary.json`

`battle-results/` is ignored by git, so this document is the tracked summary of
the championship run.

## Notes

One local tournament run initially failed because the embedded Robocode server
selected a port that was already in use. The missing run was rerun with retries,
and the final summary includes completed results for every matchup.

