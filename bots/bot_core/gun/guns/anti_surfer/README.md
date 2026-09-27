# Anti-Surfer Gun

`anti_surfer` is a second [Dynamic Cluster](../dynamic_cluster/README.md)
learner with its own KNN sample memory. It shares the wave, feature, density,
and diagnostics code of Dynamic Cluster; only its configuration differs:

- `decay_half_life` 90 observed waves, so a sample's weight halves after
  roughly two rounds of shots, and the neighbor search prefers recent samples.
- `neighbors` 7 instead of 17.
- `min_samples` 30.

The mode is `situational` in the selector, in the `knn_gf` family, with
strengths `surfer` and `adaptive_mover`. It is only constructed when a bot's
selectable gun set includes `anti_surfer`, so bots that do not list it pay no
per-turn cost.

Rationale: a wave surfer changes its movement as it learns from hits, so the
long-run profile the primary gun learns drifts away from where the surfer is
going now. See
[Adaptive Prime surfer economics](../../../../../docs/plans/adaptive-surfer-economics.md)
for the experiment that introduced it.
