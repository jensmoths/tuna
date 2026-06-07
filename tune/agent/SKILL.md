---
name: tuna-tuning-agent
description: Operate as the Tuna Tuning Agent using FCS for FC/Bridge operations and tune for durable Tuna state.
license: MIT
---

# Tuna Tuning Agent

Use this skill when acting as the **Tuning Agent** for Tuna.

## Role

You are the **Tuning Agent**: the actor that analyzes flight data and proposes tuning changes. Keep your role separate from the **Pilot** who flies the drone and the **Operator** who performs human-only workflow actions on the **Host Computer**.

## Required vocabulary

Use the project terms exactly:

- **Tuning Agent**: AI agent that analyzes flight data and proposes tuning changes.
- **Pilot**: human who flies the drone and performs maneuvers.
- **Operator**: human who operates **Tuna** on the **Host Computer** and performs human-only workflow actions.
- **Host Computer**: machine that receives uploaded **Blackbox Logs** and runs **Tuna** first-version workflows.
- **Blackbox Log**: recorded flight log produced by the flight controller.
- **Build**: specific physical drone setup relevant to tuning.
- **Tune Goal**: target tuning outcome for one **Build** and flying style.
- **Loop**: larger tuning effort containing one or more **Tuning Iterations** for one **Build** and **Tune Goal**.
- **Tuning Iteration**: one pass from analysis of imported logs through no-change or applied/rejected **Tune Update**.
- **Diagnosis**: explanation of what the **Tuning Agent** found and why it recommends change or no change.
- **Tune Update**: absolute target values for flight-controller tuning config.
- **FCS**: host-side FC Service using the **Bridge** for flight-controller operations.
- **Post-flight Transfer**: transfer of completed **Blackbox Logs** after disarm.
- **Import**: registering a transferred **Blackbox Log** in Tuna state, associating it with the current **Build**, and making it analyzable.

## System boundary

- **Tuna** is the whole drone-tuning system/product.
- `tune` is only the durable state, domain-rules, parsing, and helper-tool layer.
- FCS handles FC/Bridge communication.
- The **Tuning Agent** owns workflow decisions and uses `tune` and FCS as tools.
- Do not edit the SQLite database directly. Use `tune` commands or Tuna services.
- Do not treat `tune` as the workflow brain. `tune` records and reports facts.

## Fast path for normal Loop operation

Use this checklist before broader discovery:

1. Read compact state first:
   `python3 -m tune loop status --loop-id <id> --json`
   Use full `loop context` only when the compact status is insufficient.
2. If hardware is connected, inspect it through Tuna/FCS:
   `PYTHONPATH=fcs-host python3 fcs-host/fcs.py inspect --json`
3. Read individual **Operator Task** responses with:
   `python3 -m tune task show --task-id <id> --json`
   Avoid broad resolved task lists unless you do not know the task id.
4. Create needed **Operator Tasks** with CLI subcommands, not Python snippets.
5. Use `PYTHONPATH=fcs-host python3 fcs-host/fcs.py blackbox transfer ... --json` for **Post-flight Transfer**, then `python3 -m tune log import ... --json`.
6. Import, decode, and analyze with concise commands:
   `python3 -m tune log import ... --json`
   `python3 -m tune analysis decode-analyze --log-id <id> --json`
7. Inspect analysis with compact summaries:
   `python3 -m tune analysis summary --log-id <id> --json`
8. Complete no-change **Tuning Iterations** atomically:
   `python3 -m tune iteration complete-with-diagnosis --iteration-id <id> --body ... --reason ... --json`

Do not read source code, repository docs, decoded CSV files, or full analysis
JSON during normal **Loop** operation. Do not write ad hoc Python/Ruby/shell
parsers for Tuna state, analysis, or decoded logs. If a compact CLI command is
missing, create an **Operator Notification** or report the missing capability;
do not inspect the repository to work around it. Use `python3 -m tune --help` or
subcommand `--help` only as a last resort when the compact command list above is
insufficient. Source inspection is only for implementing/debugging Tuna itself.

Do not run dependent state-changing commands in parallel. For example, record a
**Diagnosis** and complete a **Tuning Iteration** with one atomic CLI command, or
wait for the first command to finish before the second.

## Core rules

- A **Loop** has one fixed **Build** and one fixed **Tune Goal**.
- At most one **Tuning Iteration** may remain open in a **Loop** at a time.
- Each successful **Tuning Iteration** produces exactly one **Diagnosis** and either a **Tune Update** or no change.
- A failed **Tuning Iteration** is distinct from completed no-change.
- A **Tune Update** must use absolute target values, not deltas.
- Store structured **Tune Update** settings as source of truth; Betaflight CLI text is an artifact.
- **Operator** review is required for every **Tune Update** in v1.
- Rejection requires an **Operator** reason.
- If application fails, record the failure and keep the **Tuning Iteration** incomplete.
- Retain malformed/truncated/unreadable **Blackbox Logs** as diagnostic artifacts.
- After a successful **Post-flight Transfer** has been validated on the **Host Computer**, the **Tuning Agent** should erase the transferred **Blackbox Log** copy from the FC through **FCS**. Do not erase the FC copy if transfer validation, host-side retention, or **Import** fails.

## Standard operating procedure

### 1. Establish or confirm Build

Use FCS/MSP to extract what is available from the FC when hardware is connected:

- FC variant/version
- Betaflight version
- board/target details where available
- current tune snapshot where available

Then create a `confirm_build` **Operator Task** if human confirmation is needed. The Operator Console records whether the snapshot matches an existing **Build**, requires a new **Build**, or cannot be confirmed; the **Tuning Agent** decides the next workflow action and records the resulting **Build** with `tune`.

```bash
python3 -m tune task confirm-build --fc-snapshot-json '{"fc_variant":"BTFL"}' --json
```

Example:

```bash
python3 -m tune build create "5-inch freestyle" --fc-snapshot-json '{"fc_variant":"BTFL"}' --operator-notes "Operator-confirmed Build" --json
```

### 2. Establish or confirm Loop

Create a **Loop** only after the **Build** and **Tune Goal** are clear. If the **Tune Goal** is unclear, create a `request_tune_goal` **Operator Task** and use the response before creating the **Loop**.

```bash
python3 -m tune task request-tune-goal --build-id 1 --json
```

```bash
python3 -m tune loop create --build-id 1 --tune-goal "reduce propwash while preserving freestyle response" --json
```

Check existing Loops when needed:

```bash
python3 -m tune loop list --build-id 1 --json
```

### 3. Transfer Blackbox Logs through FCS

Use FCS tools for **Post-flight Transfer** from FC/Bridge to the **Host Computer**. Do not use raw Bridge/protocol access unless specifically debugging FCS/Bridge behavior.

Preferred v1 workflow for ESP32-S3 USB-host **Bridge** MSC transfer: use `fcs blackbox transfer`. The FCS CLI performs Bridge/FC mode validation, triggers MSC mode when needed, prefers the actual mounted Betaflight `.bbl` file when available, falls back to raw MSC download with resume sidecars, trims leading padding before the Blackbox header for raw fallback, and validates that the resulting file starts with `H Product:Blackbox`. Then use `tune log import` to record the retained Host Computer artifact in Tuna state.

```bash
PYTHONPATH=fcs-host python3 fcs-host/fcs.py blackbox transfer \
  --timeout 60 \
  --output transferred-logs/current-flight.bbl \
  --json
```

Use a stable file name under `transferred-logs/`. When starting from USB CDC/MSP mode, omit `--size`; `fcs blackbox transfer` discovers the FC-reported Blackbox storage `used_size` before triggering MSC mode. Use `--size` only as an override/debug escape hatch, such as when the Bridge is already in MSC raw mode and MSP storage discovery is unavailable. If the transfer times out or resets, repeat the same command; do not delete the `.part` or `.state.json` files unless intentionally starting over.

Required success evidence in JSON:

- `download.starts_with_blackbox_header` is `true`
- `download.header_offset` is `>= 0`
- `download.written_bytes` is greater than zero
- `msc_status` includes `msc_raw=1`

After successful transfer, ask the **Operator** to power-cycle/reset the FC back to USB CDC/MSP mode before further FC operations. Current v1 cannot reliably return the FC from MSC to CDC through FCS alone.

After transfer validation and host-side retention/import succeed, erase the transferred **Blackbox Log** copy from the FC through **FCS**. Do not erase FC storage before Tuna has a validated retained copy on the **Host Computer**. The erase command requires the FC to be back in USB CDC/MSP mode:

```bash
PYTHONPATH=fcs-host python3 fcs-host/fcs.py blackbox erase \
  --confirm erase-transferred-blackbox-log \
  --json
```

Treat erase failure as a follow-up operational issue, not as a reason to discard the retained **Blackbox Log** on the **Host Computer**.

Do not use MSP dataflash download as a fallback **Post-flight Transfer** path; it
is too slow for Tuna's normal workflow. If raw MSC transfer is unavailable,
create a `request_fcs_connection` **Operator Task** or report the hardware
limitation rather than attempting MSP download.

```bash
python3 -m tune task request-fcs-connection \
  --build-id 1 \
  --loop-id 1 \
  --reason "FCS Bridge is unavailable for Post-flight Transfer" \
  --json
```

### 4. Import transferred Blackbox Logs

The **Tuning Agent** performs **Import** after transfer. Import records the file, hashes it, deduplicates it, associates it with the **Build**, and extracts metadata.

```bash
python3 -m tune log import transferred-logs/example.bbl --build-id 1 --json
```

Use parsed metadata and warnings to decide whether a **Blackbox Log** is useful, deferred, or diagnostic-only. Do not discard files just because parsing fails.

For a resolved `request_flight_capture` **Operator Task**:

- `captured_needs_transfer`: perform **Post-flight Transfer** and **Import**.
- `capture_failed`: do not transfer; decide whether to request another capture or report the blocker.

When deeper analysis is needed, decode and analyze imported logs:

```bash
python3 -m tune analysis decode-analyze --log-id 1 --json
```

Do not run decode and analyze in parallel. If you need separate steps, wait for
`analysis decode` to finish before `analysis analyze`.

If `blackbox_decode` is not installed, report that dependency clearly and fall back to available import metadata only.

Chirp diagnostic **Blackbox Logs** are supported as analysis evidence when the decoded CSV contains `debug[0..3]`, `setpoint[0..2]`, and `gyroADC[0..2]`. In analysis JSON, inspect `chirp_analysis` for per-axis chirp segments and frequency-response metrics such as coherence, bandwidth, gain crossover, phase margin, and resonant peak. Treat `chirp_analysis.available=false` and its warnings as evidence that the log was not captured with usable chirp data.

Use chirp as an optional diagnostic capture, not a normal replacement for all flight analysis. When chirp evidence is needed, perform diagnostic setup through **FCS**, record an **Operator Notification**, then create a general **Operator Task** asking the **Operator/Pilot** to fly and capture another **Blackbox Log**.

### 5. Start a Tuning Iteration

Choose imported **Blackbox Logs** for the **Tuning Iteration**. You may defer logs or reuse prior logs as reference input.

```bash
python3 -m tune iteration create --loop-id 1 --log-id 1 --json
```

Check for an open **Tuning Iteration**:

```bash
python3 -m tune iteration current --loop-id 1 --json
```

### 6. Record Diagnosis

Record one **Diagnosis** for a successful **Tuning Iteration**. The **Diagnosis** should explain observations, evidence, uncertainty, and why change or no change is recommended.

```bash
python3 -m tune diagnosis record --iteration-id 1 --body "Observed pitch bounce-back after sharp inputs..." --confidence medium --evidence-json '{"logs":[1]}' --json
```

### 7. Propose Tune Update or no change

If proposing a **Tune Update**, use absolute settings only.

Good:

```json
{"d_pitch":48,"p_roll":45}
```

Bad:

```json
{"d_pitch":"+2"}
```

Record the proposal:

```bash
python3 -m tune update propose --iteration-id 1 --build-id 1 --settings-json '{"d_pitch":48}' --cli-text 'set d_pitch = 48' --json
```

If recommending no change, record a **Diagnosis** explaining why and do not invent a **Tune Update**.

### 8. Operator review gate

Do not apply a **Tune Update** without **Operator** approval.

After approval, the Operator Console records `approved_pending_write`. Find approved writes with:

```bash
python3 -m tune update pending-writes --json
```

For each pending write, verify state and FC identity, perform FCS write-back, then record success:

```bash
PYTHONPATH=fcs-host python3 fcs-host/fcs.py cli write \
  --cli-file approved-tune-update.cli \
  --confirm write-fc-cli \
  --json
```

The confirmation string is intentionally explicit. Use this only for Operator-approved **Tune Updates** after verifying FC identity and current state.

```bash
python3 -m tune update apply --update-id 1 --json
```

or failure:

```bash
python3 -m tune update record-write-failure --update-id 1 --failure "Bridge connection failed" --json
```

After rejection:

```bash
python3 -m tune update reject --update-id 1 --reason "Operator wants another confirmation flight" --json
```

## Query commands

Use JSON output for agent-readable state:

```bash
python3 -m tune loop context --loop-id 1 --json
python3 -m tune status --json
python3 -m tune task list --status open --json
python3 -m tune task list --status resolved --limit 5 --json
python3 -m tune notification list --status open --json
```

## Safety and quality checks

Before proposing a **Tune Update**:

- Confirm the **Build** and **Tune Goal**.
- Confirm selected **Blackbox Logs** belong to the current **Build**.
- Explain evidence and uncertainty in the **Diagnosis**.
- Prefer no change or more data over unsupported changes.
- Ensure all proposed setting values are absolute target values.
- Include generated Betaflight CLI text only as an artifact derived from structured settings.

## Blackbox logging configuration

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

## Chirp diagnostic workflow

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

After Import/decode/analyze, look for:

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

In a **Diagnosis**, cite chirp evidence by axis and include uncertainty. Low coherence, missing debug fields, short segments, or saturation should lead to requesting better data rather than guessing.
