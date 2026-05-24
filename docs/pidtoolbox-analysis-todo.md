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
