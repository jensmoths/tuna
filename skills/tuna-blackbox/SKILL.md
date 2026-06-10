---
name: tuna-blackbox
description: Use the standalone Tuna Blackbox CLI for Blackbox Log metadata, decode, analysis, and segment row inspection without Tuna web/Loop/SQLite state.
license: MIT
---

# Tuna Blackbox

Use this skill when an agent needs to inspect or analyze **Blackbox Logs** without depending on the Tuna web Operator Console, Tuning Agent Loop, or SQLite database.

## Boundary

- Use `tuna-blackbox` when installed as a console script, or `python3 -m tuna_blackbox.cli` from the repository.
- Use JSON output for agent-readable behavior.
- This CLI does not require or update Tuna SQLite state.
- Do not treat analysis output as an automatic **Tune Update**. It is evidence for human or agent interpretation.
- Prefer compact JSON output. Write full analysis JSON to an artifact when it is large.

## Metadata

Parse Blackbox header metadata directly from a `.bbl` file:

```bash
tuna-blackbox metadata flight.bbl --json
```

Include or retain full metadata when needed:

```bash
tuna-blackbox metadata flight.bbl \
  --full \
  --metadata-json-file artifacts/flight.metadata.json \
  --json
```

Retain malformed, truncated, unsupported, and unreadable **Blackbox Logs** as diagnostic artifacts.

## Decode and analyze

Preferred standalone path:

```bash
tuna-blackbox decode-analyze flight.bbl \
  --output artifacts/flight.csv \
  --output-json-file artifacts/flight.analysis.json \
  --json
```

Use separate commands only when debugging or when a decoded CSV already exists:

```bash
tuna-blackbox decode flight.bbl --output artifacts/flight.csv --json
tuna-blackbox analyze artifacts/flight.csv --output-json-file artifacts/flight.analysis.json --json
```

If `blackbox_decode` is not installed or fails, report that dependency/failure clearly and fall back to available metadata.

## Segment row inspection

Use bounded row windows rather than reading entire decoded CSV files:

```bash
tuna-blackbox segment-rows artifacts/flight.csv \
  --start-row 1000 \
  --end-row 1200 \
  --fields 'time,setpoint[0],gyroADC[0]' \
  --pad-rows 20 \
  --json
```

## Evidence to inspect

Prefer compact `tuna-core analysis` views in a Tuna Loop before reading full analysis JSON:

- `analysis recordings --log-id ... --json` for internal Blackbox Log CSVs from a multi-log `.bbl`.
- `analysis compare --before-log-id ... --after-log-id ... --json` for before/after metric deltas.
- `analysis throttle-chop --log-id ... --json` for throttle-min/motor-hang evidence.
- `analysis cross-axis-flip --log-id ... --json` for roll-flip pitch/yaw disturbance evidence.

Use these analysis sections as evidence, when present:

- `quality` and `warnings`: whether the **Blackbox Log** is usable, diagnostic-only, or insufficient.
- `analysis_capabilities`: missing fields/debug modes that limit conclusions.
- `segments.high_rate`: roll/pitch/yaw setpoint activity and tracking error.
- `segments.throttle_punch`: throttle punch windows and related motor/noise behavior.
- `timing_analysis`: loop timing and sample interval evidence.
- `spectrum_analysis`: frequency peaks and noise bands.
- `filter_analysis`: filtered vs unfiltered gyro attenuation.
- `rpm_analysis`: RPM harmonic matches or missing-debug reasons.
- `motor_analysis`: motor ranges, saturation, throttle-bin summaries, and imbalance.
- `pid_term_analysis`: P/I/D/feedforward activity and D-term/P-D balance proxies.
- `chirp_analysis`: chirp frequency-response evidence when a usable chirp capture exists.

Prefer no change or more data when warnings indicate missing fields, short captures, absent maneuvers, motor saturation, or low chirp coherence.

## Chirp analysis

Chirp diagnostic **Blackbox Logs** are supported when decoded CSV contains required debug, setpoint, and gyro fields. Treat `chirp_analysis.available=false` and its warnings as evidence that the log was not captured with usable chirp data.

Do not trigger chirp automatically. Chirp is flight-safety relevant and any configuration or flight action must be handled by the controlling workflow/operator process.
