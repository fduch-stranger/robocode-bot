# Displacement Gun PIF Improvement Plan

We can improve the current `displacement` gun directly. Right now it is too
simple: it finds old target positions with about the same bullet flight time,
averages their `dx/dy`, then aims at:

```text
current enemy position + average displacement
```

That is weak because it does not ask whether the old movement looked like the
current movement. It also copies world-space movement directly, so a past "move
forward while turning left" pattern is not rotated into today's enemy heading.
It averages movement instead of replaying movement until the bullet would
actually intersect.

Robowiki's [Play It Forward](https://robowiki.net/wiki/Play_It_Forward) gives a
better model for the same gun: keep enemy movement history, find a past state
similar to the current one, then replay what happened after that past state from
the enemy's current position.
[Interpolating PIF](https://robowiki.net/wiki/PIF/Interpolating_PIF) improves
this by jumping through snapshots/displacement vectors instead of doing slow
tick-by-tick prediction.

## Concrete Example

```text
Current displacement gun:
  20 ticks ago enemy moved +80 x, -20 y
  another sample moved +60 x, +10 y
  average = +70 x, -5 y
  aim at current enemy position + (+70, -5)
```

Improved displacement gun:

```text
Find a past moment similar to now:
  similar heading
  similar velocity
  similar lateral movement
  similar wall position

Replay what happened after that past moment:
  enemy turns left
  enemy slows down
  enemy bends along wall
  enemy reverses

Stop replay when our bullet would reach that replayed position.
Aim at that endpoint.
```

## Implementation Shape

```text
1. Extend TargetPosition.
   Current history stores turn/x/y/speed.
   Add heading/direction, and possibly derived velocity components.

2. Replace average dx/dy with PIF-style replay.
   The public gun mode remains `displacement`.

3. At aim time, find historical start snapshots similar to the current enemy state:
   heading difference
   speed
   lateral speed
   advancing speed
   wall margin

4. For each candidate start snapshot, replay the following historical movement
   from the enemy's current position.

5. Normalize replay by heading.
   If the old enemy moved forward-left relative to its heading,
   replay forward-left relative to the current heading.

6. Stop each replay when:
   bullet_travelled >= distance from our fire position to replayed enemy position

7. Convert the replay endpoint into an aim bearing.

8. If multiple candidates are usable, choose the median or density-best bearing,
   not a simple average dx/dy.
```

## Key Improvement

The key improvement is rotation-normalized replay.

The current gun says:

```text
old movement was +80 x, -20 y
do +80 x, -20 y again
```

The improved gun should say:

```text
old movement was forward-left relative to enemy heading
replay forward-left relative to current enemy heading
```

## Plan

```text
Best next improvement:
  replace current displacement internals with PIF-style displacement

Do not focus on:
  thresholds or extra segmentation first

Why:
  the current formula is too crude; better prediction math should come before tuning.
```
