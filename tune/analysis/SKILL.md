---
name: tuna-blackbox-analysis
description: Use Tuna analysis tools on imported Blackbox Logs and turn machine-readable analysis into Diagnosis evidence.
license: MIT
---

# Tuna Blackbox Log Analysis

Use this skill when analyzing imported **Blackbox Logs** for a Tuna **Tuning Iteration**.

## Role and boundary

- Use `tune analysis` as the Tuning Agent-facing tool for decode/analyze outputs and analysis summaries derived from imported **Blackbox Logs**.
- Analyze only imported **Blackbox Logs** that belong to the current **Build** and are relevant to the current **Loop** / **Tune Goal**.
- Do not treat analysis output as an automatic **Tune Update**. It is evidence for a **Diagnosis**.
- Do not read decoded CSV files, full analysis JSON, or source code during normal **Loop** operation. Prefer compact JSON commands below.
- Do not write ad hoc Python/Ruby/shell parsers for Tuna state, analysis, or decoded logs. If a compact command is missing, report the missing capability.

## Decode and analyze

Preferred command after **Import**:

```bash
python3 -m tune analysis decode-analyze --log-id 1 --json
```

Use `decode-analyze` instead of separate `decode` and `analyze` during normal operation; it avoids accidentally running dependent analysis steps in parallel.

If full analysis JSON is too large for stdout, write it as an artifact while keeping CLI output concise:

```bash
python3 -m tune analysis decode-analyze \
  --log-id 1 \
  --output-json-file tune-data/analysis/log-1.analysis.json \
  --json
```

Only use separate steps when debugging or when a decoded CSV artifact already exists:

```bash
python3 -m tune analysis decode --log-id 1 --json
python3 -m tune analysis analyze --log-id 1 --json
```

Do not run `analysis decode` and `analysis analyze` in parallel for the same **Blackbox Log**.

If `blackbox_decode` is not installed or fails, report that dependency/failure clearly and fall back to available **Import** metadata only.

## Inspect concise analysis output

Start with the compact summary:

```bash
python3 -m tune analysis summary --log-id 1 --json
```

Use the summary to decide whether the **Blackbox Log** is usable evidence, diagnostic-only, or insufficient. Check:

- row count and duration
- `quality` and warnings
- `analysis_capabilities` warnings for missing fields/debug modes
- segment summaries and per-analysis warnings
- whether needed fields exist for the **Tune Goal** and maneuver type

When segment-level evidence is needed, request a bounded row window from the latest analysis rather than opening the CSV:

```bash
python3 -m tune analysis segment-rows \
  --log-id 1 \
  --segment-kind high_rate \
  --segment-index 0 \
  --fields time,setpoint[0],gyroADC[0] \
  --pad-rows 20 \
  --max-rows 200 \
  --json
```

Supported segment kinds are `high_rate`, `throttle_punch`, and `chirp`.

## Evidence to look for

Use these analysis sections as evidence, when present:

- `segments.high_rate`: roll/pitch/yaw setpoint activity, tracking error, gyro noise, and D-term noise around sharp stick inputs.
- `segments.throttle_punch`: throttle punch windows and related motor/noise behavior.
- `timing_analysis`: loop timing and sample interval evidence.
- `spectrum_analysis`: frequency peaks and noise bands.
- `filter_analysis`: filtered vs unfiltered gyro attenuation by axis/frequency band.
- `rpm_analysis`: possible RPM harmonic matches or structured missing-debug reasons.
- `motor_analysis`: motor output ranges, near-min/near-max saturation, throttle-bin summaries, and persistent motor imbalance.
- `pid_term_analysis`: P/I/D/feedforward activity, D-term spikes, possible I-term windup, feedforward activity, and P/D balance proxies.
- `chirp_analysis`: chirp segments and frequency-response metrics when a usable chirp capture exists.

Prefer no change or more data when analysis warnings say key fields are missing, captures are too short, maneuvers are absent, motors saturate, or coherence/quality is low.

## Chirp analysis

Chirp diagnostic **Blackbox Logs** are supported as analysis evidence when the decoded CSV contains `debug[0..3]`, `setpoint[0..2]`, and `gyroADC[0..2]`.

In analysis JSON, inspect `chirp_analysis` for per-axis chirp segments and frequency-response metrics such as:

- `mean_coherence_5_100hz`
- `bandwidth_hz`
- `gain_crossover_hz`
- `phase_margin_deg`
- `resonant_peak_db`

Treat `chirp_analysis.available=false` and its warnings as evidence that the **Blackbox Log** was not captured with usable chirp data.

Use chirp as optional diagnostic evidence, not a normal replacement for maneuver analysis and not an automatic **Tune Update** generator. Low coherence, missing debug fields, short segments, or motor saturation should lead to requesting better data rather than guessing.

Example useful chirp evidence shape:

```json
{
  "chirp_analysis": {
    "available": true,
    "axes": {
      "roll": {
        "mean_coherence_5_100hz": 0.9,
        "bandwidth_hz": 45.0,
        "phase_margin_deg": 55.0,
        "resonant_peak_db": 2.0
      }
    }
  }
}
```

## When analysis data is missing

The **Tuning Agent** may need different Betaflight Blackbox settings so future **Blackbox Logs** contain the data required by Tuna analysis tools.

Examples include requesting fields or modes needed for:

- gyro and unfiltered gyro comparison
- D-term noise analysis
- RPM/filter analysis
- chirp frequency-response analysis (`debug_mode = CHIRP`, high-resolution Blackbox logging, and a firmware build with CHIRP support)
- debug modes relevant to filters, RPM, or scheduler behavior
- logging rate or denominator changes

Rules:

- Treat Blackbox configuration changes as diagnostic/logging changes, not as **Tune Updates**, unless they also alter flight behavior.
- Do not silently change FC configuration. After changing diagnostic Blackbox/logging configuration through **FCS**, record an **Operator Notification** explaining what changed and why.
- **Operator** approval is not required for diagnostic-only Blackbox/logging configuration changes. If a requested setting changes flight behavior or is also a **Tune Update**, use the **Tune Update** review gate instead.
- Use **FCS** for Blackbox/logging configuration write-back; the Operator Console must not write to the FC directly.
- Record success or failure in Tuna state so later **Diagnoses** know which logs were captured with which settings.
- Prefer the smallest logging change that gives the analysis tool the missing data.
- If the requested Blackbox setting could affect performance, storage use, or flight behavior, call that out explicitly in the **Operator Notification**.

When analysis is limited by missing fields, say so in the **Diagnosis** or next-step recommendation instead of guessing.

## Chirp diagnostic capture setup

Chirp is an active setpoint excitation used to estimate control-loop frequency response. It complements normal maneuver analysis and is flight-safety relevant.

Rules:

- Do not trigger chirp automatically from Tuna.
- Do not treat chirp-derived metrics as an automatic **Tune Update**.
- The **Tuning Agent** owns chirp diagnostic setup through **FCS** when hardware is connected; do not ask the **Operator** to configure chirp manually as a normal workflow step.
- After chirp setup, create an **Operator Notification** describing changed Blackbox/logging settings, then create a general `request_flight_capture` **Operator Task** for the follow-up flight and **Blackbox Log** capture.
- The **Pilot** flies the chirp maneuver in open space and remains responsible for safe flight.
- Use chirp results as evidence in a **Diagnosis**; any resulting **Tune Update** still requires **Operator** review.

Expected setup for a useful chirp **Blackbox Log**:

- Betaflight firmware built with CHIRP support.
- `debug_mode = CHIRP`.
- High-resolution Blackbox logging enabled when available.
- `CHIRP` assigned to an AUX switch.
- Full chirp captures for roll, pitch, and yaw; toggling the switch cycles axes.
- Avoid motor saturation during chirp.

In a **Diagnosis**, cite chirp evidence by axis and include uncertainty.