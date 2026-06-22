# PIDtoolbox-inspired analysis TODO

Tuna should use Betaflight `blackbox_decode` for decoding and build repeatable JSON analysis on top. Blackbox Explorer and PIDtoolbox remain human reference/validation tools.

References checked:

- PIDtoolbox GitHub: https://github.com/bw1129/PIDtoolbox
- PIDtoolbox overview/architecture notes: https://deepwiki.com/bw1129/PIDtoolbox/1-overview
- PIDtoolbox step response notes: https://deepwiki.com/bw1129/PIDtoolbox/4.3-step-response-analysis
- Betaflight Blackbox Explorer: https://blackbox.betaflight.com/

## Implemented first pass

- Decode imported **Blackbox Logs** to CSV with `blackbox_decode`.
- Store decoded CSV artifacts in SQLite.
- Store JSON analysis artifacts in SQLite.
- Field normalization for decoded headers with units, such as `time (us)`.
- Basic quality checks: duration, gyro fields, setpoint fields, motor fields, PID-term fields.
- Basic activity summary: max setpoint by axis, high-rate sample counts, throttle range, motor saturation sample count.
- Basic setpoint-vs-gyro tracking error by axis.
- Basic rough noise proxy using mean/max absolute sample-to-sample delta for gyro, unfiltered gyro, and D-term fields.
- Simple web Operator Console analysis list/detail pages.

## TODO: log loading and quality

- Detect gaps/dropouts and estimate effective logging rate.
- Detect arming/disarming segments and trim idle ground time.
- Detect Blackbox frame types and skipped/corrupt frames from decoder output where available.
- Detect missing or unusable gyro, setpoint, motor, PID-term, throttle, debug, RPM, and filter-related fields.
- Summarize firmware, craft name, PID profile, rate profile, filters, debug mode, and logging rates together with analysis.
- Compare multiple logs from the same **Loop** and identify before/after pairs.

## TODO: maneuver and segment detection

- Detect snap rolls, snap flips, yaw spins, throttle punches, throttle cuts, propwash recovery segments, and steady hover/cruise segments.
- Score segment usefulness for tuning by axis, stick input size, duration, and motor saturation.
- Exclude segments with crashes, failsafe, RX loss, takeoff/landing bumps, or obvious clipping.
- Allow the **Tuning Agent** to cite selected segment IDs in a **Diagnosis**.

## TODO: step response / time-domain response

PIDtoolbox has step response analysis for roll/pitch/yaw and uses setpoint/gyro data to evaluate controller response. Tuna should add machine-readable equivalents:

- Find step-like setpoint inputs by axis.
- Estimate latency/delay between setpoint and gyro response.
- Estimate rise time, overshoot, undershoot, settling behavior, and bounce-back.
- Compute per-axis response summaries across many events.
- Compare response between logs and after **Tune Updates**.
- Flag under-damped, over-damped, sluggish, or overshooting axes.
- Support smoothing levels for response analysis.

## TODO: spectral / frequency-domain analysis

PIDtoolbox is known for spectral analysis and frequency-vs-throttle views. Tuna should add:

- FFT/PSD summaries for gyro, unfiltered gyro, D-term, motor, and debug fields.
- Frequency peaks by axis and signal.
- Noise energy bands, especially low/mid/high frequency bands relevant to filters.
- Frequency-vs-throttle heatmap data for gyro, D-term, motor, and RPM-related fields.
- Before/after filter comparison summaries.
- Identification of frame resonance, motor noise, RPM harmonics, and D-term amplification.
- Machine-readable warnings when filter settings appear too light/heavy for observed noise.

## TODO: filter analysis

- Compare filtered gyro vs unfiltered gyro where both are logged.
- Estimate attenuation by frequency band.
- Detect excessive filtering from lag/response degradation.
- Detect insufficient filtering from D-term/noise metrics.
- Summarize dynamic notch/RPM filter effectiveness when relevant fields are available.
- Detect when required Blackbox fields/debug modes are missing and create a clear recommendation for the **Tuning Agent** to request a Blackbox logging configuration change.
- Track which **Blackbox Logs** were captured before/after diagnostic Blackbox setting changes.

## TODO: motor and saturation analysis

- Motor output range and saturation by motor.
- Time spent near min/max motor output.
- Desync-like or oscillatory motor patterns where detectable.
- Throttle-dependent motor noise summaries.
- Motor imbalance indicators and persistent motor offsets.

## TODO: PID term analysis

- P/I/D/feedforward ranges and rough noise by axis.
- D-term noise and D-term spikes around throttle changes.
- I-term windup or slow recovery indicators.
- Feedforward tracking and setpoint transition behavior.
- P/D balance indicators using response and D-term noise together.

## TODO: visualization artifacts

- Generate small static SVG/PNG plots for Operator Console review.
- Include setpoint vs gyro overlays for selected segments.
- Include rough spectrum plots and throttle-frequency heatmaps.
- Keep JSON metrics as source of truth; plots are review artifacts.

## TODO: tuning recommendation support

- Convert analysis metrics into evidence snippets for **Diagnosis**.
- Provide suggested areas to consider, not automatic changes: P, I, D, feedforward, filters, dynamic idle, rates.
- Compare current analysis to previous **Tuning Iterations** in the same **Loop**.
- Track whether a **Tune Update** improved or worsened response/noise.

## Implemented second pass

- Basic high-rate segment detection for roll, pitch, and yaw setpoint activity.
- Basic throttle-punch segment detection using throttle command thresholding.
- Segment summaries include timing, sample count, max setpoint/gyro where applicable, throttle peak where applicable, and motor saturation sample count.
- Operator Console analysis detail page shows segment JSON.

## Implemented third pass

- High-rate segments include per-segment tracking error and rough gyro/D-term noise metrics.
- Segments include `raw_data_ref` with CSV path, row range, and time range so the **Tuning Agent** can inspect the underlying decoded rows directly.
- Operator Console analysis detail page now shows a concise segment table before raw segment JSON.


## Implemented fourth pass

- Added `tuna-core analysis segment-rows --log-id ... --segment-kind ... --segment-index ... --json`.
- Segment row extraction returns selected decoded CSV rows using segment `raw_data_ref`.
- Supports selected fields, row padding, and max row limits so the **Tuning Agent** can inspect maneuver source data without loading an entire CSV.

## Implemented fifth pass

- Added timing summaries with nominal/effective logging rate estimates.
- Added timing gap/dropout detection with row/time ranges and estimated missing sample counts.
- Added first-pass FFT spectrum summaries for gyro, unfiltered gyro, D-term, motor, and debug fields.
- Spectrum summaries include top frequency peaks and low/mid/high frequency band energy fractions.
- Operator Console analysis detail page shows timing and spectrum JSON.

## Implemented sixth pass

- Added structured `analysis_capabilities` warnings that name missing Blackbox fields/debug modes limiting stronger **Diagnosis** evidence.
- Added active/armed flight window detection with leading/trailing idle trim metadata and raw row references.
- Added first-pass frequency-vs-throttle heatmap JSON for spectral fields using throttle bins.
- Added performance regression tests for local analysis tools on large decoded CSV inputs.

## Implemented seventh pass

- Added `filter_analysis` JSON comparing filtered `gyroADC[*]` against unfiltered `gyroUnfilt[*]` by frequency band.
- Filter analysis reports per-axis attenuation ratio, attenuation dB, and reduction fraction.
- Added filter attenuation warnings for missing fields, insufficient samples, and low high-frequency attenuation.
- Operator Console analysis detail page shows filter analysis JSON.

## Implemented eighth pass

- Added `noise_peaks` JSON with prominent gyro, unfiltered gyro, D-term, motor, and debug spectrum peaks.
- Noise peaks include frequency region and conservative classifications such as possible frame resonance, motor harmonic, and D-term amplification.
- Added first-pass `rpm_analysis` JSON using debug field spectra when available.
- RPM analysis reports possible harmonic matches between debug peaks and gyro/D-term/motor peaks, or a structured missing-debug reason.

## Implemented ninth pass

- Added first-pass `step_response` JSON for roll, pitch, and yaw setpoint steps.
- Step response events estimate latency, rise time, overshoot, undershoot, settling error, and bounce-back.
- Per-axis step response summaries include event counts, mean response metrics, and flags such as sluggish, slow rise, overshooting, bounce-back, and poor settling.

## Implemented tenth pass

- Added first-pass `motor_analysis` JSON with per-motor min/max/mean output.
- Motor analysis reports near-min/near-max samples and fractions, persistent offsets from fleet mean, and imbalance score.
- Motor analysis includes throttle-bin summaries and warnings for saturation or persistent motor imbalance.

## Implemented eleventh pass

- Added first-pass `pid_term_analysis` JSON for P/I/D/feedforward terms by axis.
- PID term analysis reports term ranges/means, D-term noise and spike counts, D-term spikes near throttle changes, I-term windup proxies, feedforward activity on setpoint transitions, and P/D balance proxies.
- PID term analysis emits machine-readable flags for D-term spikes, throttle-coupled D-term spikes, possible I-term windup, inactive feedforward on setpoint steps, and P/D dominance.

## Current noise/filter support

- Implemented: rough time-domain noise proxies for gyro, unfiltered gyro, and D-term using sample-to-sample absolute deltas.
- Implemented: per-segment rough gyro/D-term noise for high-rate segments.
- Implemented: active-flight-only rough noise, spectrum, filter, motor, PID, and step-response summaries.
- Implemented: first-pass FFT spectrum summaries for gyro, unfiltered gyro, D-term, motor, and debug fields.
- Implemented: first-pass frequency-vs-throttle heatmap JSON for gyro, unfiltered gyro, D-term, motor, and debug fields.
- Implemented: windowed frequency-vs-throttle heatmap JSON using contiguous windows and mean throttle per window.
- Implemented: filter attenuation estimates comparing filtered gyro vs unfiltered gyro by frequency band.
- Implemented: first-pass RPM harmonic detection from debug-field spectral peaks.
- Implemented: first-pass step response and time-domain setpoint response summaries.
- Implemented: first-pass motor output, saturation, throttle-bin, and imbalance summaries.
- Implemented: first-pass PID term, D-term spike, I-term windup, feedforward, and P/D balance summaries.
- Implemented: first-pass evidence-only filter/PID classifications, propwash recovery windows, segment-gated summaries, and capture-plan recommendations.
- Not implemented yet: full debug-mode-specific dynamic notch/RPM filter effectiveness summaries.

## Implemented twelfth pass

- Added `active_analysis` with active-flight-only metrics so idle/ground rows do not dominate noise/filter/PID evidence.
- Added `windowed_frequency_throttle_heatmap`, preserving the older concatenated heatmap while providing contiguous-window throttle/frequency evidence.
- Added `propwash_analysis` for first-pass throttle-recovery/propwash windows.
- Added `segment_gated_analysis` for clean high-rate segment summaries excluding motor-saturated segments.
- Added `tuning_evidence` containing evidence-only filter classifications, PID response classifications, and capture-plan recommendations.
- Expanded `analysis compare` with step-response, filter, noise, RPM/filter, propwash, chirp, and evidence classification deltas.
- Added compact `tuna-core analysis` views: `filter-evidence`, `pid-response`, `noise-peaks`, `rpm-filter`, `propwash`, and `capture-plan`.

## Implemented thirteenth pass

- Added standalone `tuna-blackbox` compact evidence views for decoded CSV inputs: `filter-evidence`, `pid-response`, `noise-peaks`, `rpm-filter`, `propwash`, and `capture-plan`.
- Added first-pass before/after `outcome_summary` classification (`improved`, `worse`, `mixed`, or `inconclusive`) based on lower-is-better response/noise/saturation metrics.
- Added debug-mode-family labeling and first-pass RPM/filter residual harmonic evidence for RPM/filter debug modes while keeping CHIRP logs separate.
- Real-log validation tightened CHIRP gating so generic debug fields no longer create false CHIRP segments, added capture-plan warnings for unknown debug mode, and reports conflicting filter evidence as `mixed_filter_evidence`.

## Implemented chirp analysis MVP

- Added decoded-CSV Blackbox header setting extraction for analysis inputs that include header setting rows before the data header.
- Added `chirp_analysis` JSON for logs containing `debug[0..3]`, `setpoint[0..2]`, and `gyroADC[0..2]`.
- Chirp analysis segments active chirps by `debug[1]` axis marker (`0=roll`, `1=pitch`, `2=yaw`, `-1=inactive`).
- Per usable chirp segment, Tuna estimates a Welch setpoint-to-gyro transfer function summary with coherence, bandwidth, gain crossover, phase margin, and resonant peak metrics.
- Chirp analysis is evidence-only: it does not create **Tune Updates** automatically.

## TODO: Blackbox logging configuration support

- Implemented first pass: analysis warnings name missing Blackbox fields or debug modes needed for a stronger **Diagnosis**.
- Implemented: separate **Operator Notification** storage and UI for diagnostic Blackbox setting changes made by the **Tuning Agent** through FCS.
- Add FCS helpers for reading and writing relevant Betaflight Blackbox settings.
- Record Blackbox setting snapshots with imported **Blackbox Logs** so the **Tuning Agent** knows which analysis features are valid for each log.
- Keep diagnostic Blackbox setting changes separate from **Tune Updates** unless the setting also affects flight behavior.

## TODO: chirp validation and workflow

- Validate `chirp_analysis` on a real chirp **Blackbox Log** captured with CHIRP-enabled Betaflight, `debug_mode = CHIRP`, high-resolution Blackbox logging, and full roll/pitch/yaw chirp segments.
- Verify decoded CSV header parsing against real `blackbox_decode` output for chirp logs, especially `debug_mode`, `blackbox_high_resolution`, chirp parameter rows, and field names.
- Verify high-resolution scaling assumptions for setpoint/gyro in decoded CSV chirp logs.
- Compare Tuna chirp metrics against Betaflight Configurator's Autotune tab and `bf_controller_tuning` on the same log.
- Implemented: general `request_flight_capture` **Operator Task** kind/template for requesting another flight and **Blackbox Log** capture; chirp-specific setup belongs in prior FCS writes plus **Operator Notifications**.
- Add a fixture real chirp log or trimmed decoded CSV fixture once available, with regression tests for segment detection and frequency-response metrics.
