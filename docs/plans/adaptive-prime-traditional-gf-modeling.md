# Adaptive Prime Traditional GF Modeling

Adaptive Prime BasicGFSurfer telemetry showed `traditional_gf` can receive a
high switch score while producing weak real hit rate. Treat this as a modeling
and calibration problem before changing switch thresholds again.

## Current Evidence

- A 36-round BasicGFSurfer run showed `traditional_gf` fired `173` shots with
  `0.1098` total hit rate.
- In the same run, `traditional_gf` switch calibration showed average adjusted
  switch score `0.2622` but post-switch hit rate `0.1875`.
- `dynamic_cluster` was healthier in that run: `789` fired shots, `0.1952`
  total hit rate, and `0.2473` post-switch hit rate.
- This suggests `traditional_gf` may be over-trusted by virtual scoring or too
  coarse for surfer-style movement.

## Hypothesis

The current `traditional_gf` aim model is a single decayed global guess-factor
histogram per target. Selector scoring may use current segment evidence, but
the actual `traditional_gf` bearing still comes from the global profile. Against
surfers, the best guess factor often depends on distance, wall margin, lateral
velocity, acceleration, velocity-change age, and firepower.

## Modeling Candidates

1. Add segmented traditional-GF profiles with global fallback.
   - Useful dimensions: distance, wall margin, lateral velocity, acceleration,
     velocity-change age, and firepower.
   - Keep the existing global profile as the fallback when segment evidence is
     thin.

2. Blend global and segment profiles by confidence.
   - Start with mostly global behavior.
   - Increase segment influence as segment visits grow.
   - Avoid hard switching to low-sample segment peaks.

3. Add telemetry before major policy changes.
   - Report global GF peak, segment GF peak, selected GF, segment visits, and
     selected profile source/blend.
   - Compare those fields with post-switch real hit rate.

4. Tune histogram smoothing after segmentation.
   - Test `traditional_gf_smoothing_bins` around `0.75`, `1.0`, and `1.25`.
   - Avoid changing smoothing and segmentation in the same comparison unless a
     prior run already isolates the issue.

5. Tune decay after segmentation.
   - Test `traditional_gf_decay` around `0.96`, `0.975`, and `0.985`.
   - Faster decay may help if surfer behavior changes faster than the current
     global profile adapts.

6. Consider stricter switch scoring.
   - Keep near-miss virtual score for learning.
   - Consider a stricter hit-likelihood score or mode-specific calibration
     penalty for switching if high virtual score still fails to convert.

## Validation Plan

1. Run forced-mode checks for old `traditional_gf`.
2. Add segmented/profile telemetry and validate telemetry audit.
3. Run forced-mode checks for segmented `traditional_gf`.
4. Compare old vs segmented with 24-36 round BasicGFSurfer checks.
5. Run Diamond if available before making broader policy changes.
6. Only tune `traditional_gf` switch thresholds after model and calibration
   evidence is collected.

Keep `gun.eval_wave_visit` diagnostic-only. It can explain candidate behavior,
but it is not direct proof that a gun should switch live.
