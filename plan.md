# Tuna Blackbox tuning-analysis implementation plan

This plan turns the current `tuna_blackbox` metric summaries into stronger,
Tuning Agent-ready evidence for filter and PID tuning. Analysis remains
evidence-only: it must not create **Tune Updates** automatically.

## Goals

- Prefer active-flight and clean-maneuver evidence over whole-log metrics.
- Combine existing metrics into confidence-scored evidence bundles that the
  **Tuning Agent** can cite in a **Diagnosis**.
- Expose compact CLI views so normal **Loop** operation does not require loading
  full analysis JSON.
- Make missing-field and missing-maneuver conclusions actionable through capture
  recommendations.

## Implementation phases

1. Active-flight and segment-gated metrics
   - Add active-flight-only rough noise, spectrum, filter attenuation, motor,
     PID-term, and step-response summaries.
   - Add clean high-rate segment summaries excluding motor-saturated segments.
   - Verify with tests that idle/ground rows do not dominate active metrics.

2. Windowed throttle-frequency heatmap
   - Replace concatenated-by-throttle interpretation with a windowed heatmap
     derived from contiguous windows and mean throttle per window.
   - Keep the previous heatmap for compatibility, but prefer the windowed view in
     evidence bundles.
   - Verify with low/high-throttle synthetic frequency tests.

3. Filter evidence bundle
   - Combine filtered-vs-unfiltered attenuation, D-term high-frequency energy,
     D-term spikes, response lag, and RPM/debug evidence.
   - Output conservative classifications such as `possibly_too_light`,
     `possibly_too_heavy`, `no_strong_filter_evidence`, or `inconclusive`.
   - Include evidence snippets and confidence, not setting recommendations.

4. PID response evidence bundle
   - Combine step response, P/D balance, D-term noise, I-term windup, and
     feedforward activity.
   - Produce per-axis response classifications with supporting evidence.

5. Maneuver-specific analysis
   - Add first-pass propwash/throttle-recovery segment detection.
   - Extend cross-axis flip evidence beyond roll-only over time.
   - Score segment usefulness and mark invalid reasons such as motor saturation.

6. Debug-mode-aware RPM/dynamic-notch evidence
   - Carry Blackbox `debug_mode` into RPM/filter evidence.
   - Distinguish CHIRP logs from RPM/filter-debug logs.
   - Compare motor/debug harmonic peaks against filtered gyro and D-term residual
     energy where fields are available.

7. Expanded before/after comparison
   - Compare step response, chirp metrics, filter attenuation, noise peaks,
     D-term spikes, RPM/filter evidence, propwash metrics, and motor saturation.
   - Keep the output compact for **Tuning Agent** use.

8. Capture-plan recommendations
   - Generate a compact capture plan from missing fields, low-quality captures,
     absent maneuvers, motor saturation, missing debug modes, and low chirp
     coherence.
   - Include recommended Blackbox fields/debug modes and maneuver requests.

9. Compact CLI views
   - Add `tuna-core analysis` views for filter evidence, PID response, noise
     peaks, RPM/filter evidence, propwash, and capture plan.
   - Prefer these views in the Tuning Agent skill and Operator Console over full
     JSON when possible.

10. Chirp validation and future direct parsing
    - Validate against real CHIRP **Blackbox Logs**.
    - Compare metrics against Betaflight Configurator/PIDtoolbox references.
    - Consider direct `.bbl` chirp extraction later if CSV decoding loses needed
      metadata.

## Success criteria

- `pytest tests/test_analysis*.py tests/test_tune_cli.py` passes.
- Full analysis JSON contains active-flight and evidence outputs without removing
  existing keys.
- Compact CLI commands return bounded JSON suitable for the **Tuning Agent**.
- Evidence output states uncertainty and missing-data reasons rather than making
  automatic tune changes.

## Implementation status

Implemented in the current pass:

- `active_analysis` for active-flight-only metrics.
- `segment_gated_analysis` with clean high-rate segment summaries and segment
  usefulness/invalid-reason scoring.
- `windowed_frequency_throttle_heatmap` while retaining the older heatmap.
- `propwash_analysis` for first-pass throttle-recovery windows.
- `tuning_evidence` with filter diagnosis, PID response classification, and
  capture-plan recommendations.
- Expanded before/after comparison, including an `outcome_summary`.
- Compact `tuna-core analysis` and standalone `tuna-blackbox` evidence views.
- First-pass debug-mode-family RPM/filter residual harmonic evidence.

Still requires real **Blackbox Log** validation:

- Threshold calibration for filter/PID/propwash classifications.
- Full debug-mode-specific dynamic notch/RPM semantics.
- Real CHIRP fixture validation against Betaflight Configurator/PIDtoolbox.

## Real-log validation notes

Initial validation against `reallogs/btfl_all.01.csv` through
`reallogs/btfl_all.05.csv` found:

- The first three recordings are too short for tuning analysis and correctly
  produce capture-plan recommendations for more useful data.
- `btfl_all.04.csv` is usable and produces high-rate/throttle-chop evidence,
  while still asking for RPM/filter debug data because no debug fields are
  present.
- `btfl_all.05.csv` is usable but has no high-rate setpoint segments; sparse
  D-term spikes over a very large sample count initially over-classified filter
  risk, so evidence now requires a meaningful spike fraction or
  throttle-coupled spikes before using D-term spikes as a classification driver.

Additional validation against `reference-logs/`, `transferred-logs/`, and
`reallogs/tinywhoop/` found:

- Several transferred artifacts decode to multiple internal recordings, including
  short/empty diagnostic recordings; retaining and marking them unusable is the
  right behavior.
- Generic debug fields in Betaflight 4.5.2 reference logs were initially being
  misread as CHIRP axis markers. `chirp_analysis` now requires `debug_mode =
  CHIRP`/`97` or `chirp_*` settings before returning CHIRP segments.
- Usable reference/tinywhoop recordings often contain debug fields but no parsed
  `debug_mode`; capture plans now call out that RPM/dynamic-notch conclusions are
  limited until the debug mode is known.
- Real recordings can show both strong high-frequency attenuation and D-term
  spike evidence; those are now reported as `mixed_filter_evidence` instead of a
  one-sided filter classification.
