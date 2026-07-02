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

## Latest Checks

- `adaptive-traditional-gf-segment-12-48-basic-gf-surfer-24`: Adaptive won
  `2123` to `1532` with firsts `15-9`. `traditional_gf` fired `115` shots with
  `0.0957` hit rate; profile diagnostics had `164` blended samples and `214`
  global samples.
- `adaptive-traditional-gf-forced-12-basic-gf-surfer`: forced
  `traditional_gf` lost `400` to `1388`, firsts `3-9`, with `0.0875`
  `traditional_gf` hit rate. Treat this as evidence that the model still needs
  work, not only switch-threshold tuning.
- `adaptive-traditional-gf-forced-profile-smoke-6`: verified decoupled
  `gun.traditional_gf_profile` sampling in forced mode with `28` profile events.
- `adaptive-traditional-gf-smooth-075-forced-basic-gf-surfer-12`: forced
  smoothing `0.75` nearly tied on score, `865` to `863`, with
  `traditional_gf` hit rate `0.1218`.
- `adaptive-traditional-gf-smooth-100-forced-basic-gf-surfer-12`: forced
  smoothing `1.0` nearly tied on score, `877` to `875`, with the best forced
  smoothing hit rate in this sweep at `0.1408`.
- `adaptive-traditional-gf-smooth-125-forced-basic-gf-surfer-12`: default
  smoothing `1.25` won `883` to `844`, with `traditional_gf` hit rate `0.1348`.
- `adaptive-traditional-gf-smooth-100-normal-basic-gf-surfer-24`: normal
  Adaptive with smoothing `1.0` won `2029` to `1760`, but
  `traditional_gf` hit rate dropped to `0.075`. Do not change the default
  smoothing from `1.25` based on current evidence.
- `adaptive-traditional-gf-decay-096-forced-basic-gf-surfer-12`: decay `0.96`
  lost `816` to `1021`; forced `traditional_gf` did not become available and
  the bot fell back to `linear`/`dynamic_cluster`.
- `adaptive-traditional-gf-decay-0975-forced-basic-gf-surfer-12`: decay
  `0.975` lost `611` to `1219` despite `traditional_gf` hit rate `0.1504`.
  Do not change the default decay from `0.985` based on current evidence.
- `adaptive-traditional-gf-error-forced-basic-gf-surfer-12`: added GF-error
  telemetry. Forced `traditional_gf` lost `621` to `1187` with hit rate
  `0.1486`; production waves showed average actual GF `0.166`, aim GF `0.320`,
  signed error `-0.154`, and abs error `0.550`.
- Center-shrink experiments did not improve hit score. Factor `0.5` reduced
  abs GF error to `0.390` but dropped hit rate to `0.1012`; factor `0.75`
  also dropped hit rate to `0.1004`. Do not set a non-`1.0` centering default
  from current evidence.
- `adaptive-traditional-gf-coarse-8-36-forced-basic-gf-surfer-12`: coarse
  segment profiles won `1011` to `806`, firsts `7-5`, and raised forced
  `traditional_gf` hit rate to `0.1910`. Profile source shifted mostly to
  `coarse_blend`.
- `adaptive-traditional-gf-coarse-8-36-normal-basic-gf-surfer-12`: normal
  Adaptive with coarse profiles won `1020` to `885`, firsts `7-5`. The
  comparable no-coarse normal run lost by score, `909` to `942`, despite
  firsts `7-5`. Set shared traditional-GF coarse defaults to min/full `8/36`.
- `adaptive-traditional-gf-baseline-diamond-24`: Diamond validation is currently
  unusable in this environment because the legacy Diamond bot repeatedly throws
  movement exceptions and cannot write its `Diamond.data/error.log`.

## Hypothesis

The current `traditional_gf` aim model is a single decayed global guess-factor
histogram per target. Selector scoring may use current segment evidence, but
the actual `traditional_gf` bearing still comes from the global profile. Against
surfers, the best guess factor often depends on distance, wall margin, lateral
velocity, acceleration, velocity-change age, and firepower.

## Modeling Candidates

1. Add segmented traditional-GF profiles with global fallback. Started with
   Adaptive-specific config, then lowered the segment blend warmup to
   `traditional_gf_segment_min_samples=12` and
   `traditional_gf_segment_full_weight_samples=48` after the first telemetry
   check showed the initial 18/80 warmup rarely let segment evidence participate.
   Added coarse segment fallback keyed by distance, lateral speed, and wall
   margin. Traditional GF now defaults coarse min/full to `8/36` because
   BasicGFSurfer forced and normal checks improved.
   - Useful dimensions: distance, wall margin, lateral velocity, acceleration,
     velocity-change age, and firepower.
   - Keep the existing global profile as the fallback when segment evidence is
     thin.

2. Blend global and segment profiles by confidence.
   - Start with mostly global behavior.
   - Increase segment influence as segment visits grow.
   - Avoid hard switching to low-sample segment peaks.

3. Add telemetry before major policy changes. Started by adding
   `gun.traditional_gf_profile` plus optional `track` fields for global GF,
   segment GF, selected GF, profile weights, blend, and source.
   - Report global GF peak, segment GF peak, selected GF, segment visits, and
     selected profile source/blend.
   - Keep profile sampling independent from switch-decision sampling so forced
     gun tests expose model behavior.
   - Compare those fields with post-switch real hit rate.

4. Tune histogram smoothing after segmentation.
   - Test `traditional_gf_smoothing_bins` around `0.75`, `1.0`, and `1.25`.
   - Adaptive exposes `ROBOCODE_ADAPTIVE_TRADITIONAL_GF_SMOOTHING_BINS` so
     sweep runs do not require code edits.
   - Current sweep does not justify changing the default from `1.25`.
   - Avoid changing smoothing and segmentation in the same comparison unless a
     prior run already isolates the issue.

5. Tune decay after segmentation.
   - Test `traditional_gf_decay` around `0.96`, `0.975`, and `0.985`.
   - Adaptive exposes `ROBOCODE_ADAPTIVE_TRADITIONAL_GF_DECAY` for experiment
     runs.
   - Current sweep does not justify changing the default from `0.985`.
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
