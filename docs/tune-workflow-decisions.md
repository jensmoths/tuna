# Tune workflow decisions

Decisions recorded before implementing the Tuna workflow model.

See `docs/domain-model.md` for canonical Tuna vocabulary and domain rules.

## Naming and boundaries

- **Tuna** is the whole drone-tuning system/product.
- `tuna-core` is the Python package and helper CLI used by the **Tuning Agent**.
- `tuna-core` owns durable state, SQLite persistence, domain rules, deterministic helpers, and Blackbox Log metadata extraction.
- `tuna-core` is not the workflow brain and should not decide what happens next in a **Loop**.
- The **Tuning Agent** owns workflow decisions and may use `tuna-core`, FCS, and Pi skills.
- The **Operator** performs human-only actions and review decisions.
- The **Pilot** flies and generates **Blackbox Logs**.


## CLI/API boundary

- `tuna-fcs` is a first-class JSON CLI for hardware operations and must not read or write Tuna SQLite state.
- `tuna-blackbox` is a first-class JSON CLI for Blackbox Log metadata, decode, and analysis without requiring Tuna SQLite state.
- `tuna-core` is the agent-facing JSON CLI for Tuna durable state, domain rules, Host Computer artifacts, and analysis records; it must not talk directly to the flight controller.
- The **Tuning Agent** sequences `tuna-fcs`, `tuna-blackbox`, and `tuna-core`: use FCS for FC/Bridge/direct-USB actions, use standalone Blackbox analysis where possible, then use `tuna-core` to record/import/query the resulting Tuna state.
- `tuna-core` commands are grouped by Tuna resource/lifecycle: `loop`, `build`, `task`, `notification`, `log`, `analysis`, `iteration`, `diagnosis`, and `update`.
- `tuna-core log` is for retained/imported **Blackbox Log** artifacts on the **Host Computer**.
- `tuna-blackbox` is for decode/analyze outputs and analysis summaries derived from imported **Blackbox Logs**.


Common CLI environment variables:

- `TUNA_DB`: default SQLite Tuna database path for `python3 -m tuna_core` when `--db` is omitted.
- `FCS_CONNECTION`: default FCS connection type (`bridge` or `usb`) for `tuna-fcs` hardware commands when `--connection` is omitted.
- `FCS_BRIDGE_HOST`: default FCS Bridge host for `tuna-fcs` hardware commands and Tune Operator Task defaults when `--bridge-host` is omitted.
- `FCS_USB_DEVICE`: default direct USB serial device for `tuna-fcs` hardware commands when `--usb-device` is omitted; if unset, FCS attempts auto-detection.
- `TUNA_LOG_STORAGE_DIR`: default managed Host Computer storage directory for `tuna-core log import`.
- `TUNA_DECODED_LOG_DIR`: default decoded CSV output directory for `tuna-blackbox decode` and `tuna-blackbox decode-analyze`.
- `TUNA_BLACKBOX_DECODER`: default Blackbox decoder command for `tuna-blackbox decode` and `tuna-blackbox decode-analyze`.

Explicit CLI flags override environment defaults. The Operator Console supervisor exports `TUNA_DB` and, when available, `FCS_BRIDGE_HOST` to the Tuning Agent process so routine commands can omit those repeated options.

## Storage

- Use SQLite for durable Tuna state/history.
- Store imported **Blackbox Logs**, **Builds**, **Loops**, **Tuning Iterations**, **Diagnoses**, and **Tune Updates**.
- Retain malformed, truncated, unsupported, and unreadable **Blackbox Logs** as diagnostic artifacts.

## Tune Update representation

- A **Tune Update** must be absolute target values, not only deltas.
- Structured settings are the source of truth.
- Generated Betaflight CLI text may be stored as an application artifact.
- Example source-of-truth shape:

```json
{
  "settings": {
    "p_pitch": 56,
    "i_pitch": 84,
    "d_pitch": 46,
    "p_roll": 52,
    "i_roll": 80,
    "d_roll": 42
  }
}
```

## Operator review

- **Operator** review is required for every proposed **Tune Update** in v1.
- No automatic write-back without **Operator** approval.
- Approval in the web Operator Console means approved for **Tuning Agent** write-back through **FCS**; the web UI does not write to the FC.
- Rejection requires an **Operator** reason.
- Application failure leaves the **Tuning Iteration** open and records the failure.
- **Tune Update** statuses include `proposed`, `approved_pending_write`, `write_failed`, `applied`, and `rejected`.

## Operator Console and Operator Tasks

- Use a simple local Flask web UI as the Operator Console.
- The Operator Console is local-only by default (`127.0.0.1`).
- The Operator Console owns the Pi RPC supervisor for running Pi as the
  **Tuning Agent**; see `docs/pi-tuning-agent-rpc.md`.
- Use one persistent Pi session per **Loop**.
- The Operator Console shows Tuning Agent status by default, not the full Pi
  transcript.
- Keep the UI plain black and white; prioritize clear review UX over visual styling.
- The Operator Console shows dashboard state, **Operator Tasks**, **Operator Notifications**, **Tune Updates**, and imported **Blackbox Logs**.
- **Operator Tasks** are durable structured requests from the **Tuning Agent** to the **Operator**.
- **Operator Tasks** are not free-form chat; they are review/confirmation/action cards with structured payloads and responses.
- The **Tuning Agent** creates **Operator Tasks** when it needs human input.
- **Operator Notifications** are durable informational records, stored separately from **Operator Tasks**, for actions the **Tuning Agent** already performed or facts the **Operator** should know.
- The **Tuning Agent** records **Operator Notifications** for diagnostic-only Blackbox/logging setting changes it already made through **FCS**; these do not require **Operator** approval.
- The Operator Console records **Operator Task** responses into `tuna-core` state.
- The Operator Console records **Operator Notification** acknowledgements into `tuna-core` state.
- For `confirm_build` tasks, the Operator Console records whether the FC snapshot matches an existing **Build**, requires a new **Build**, or cannot be confirmed; the **Tuning Agent** decides the next workflow action.
- For `request_tune_goal` tasks, the Operator Console records the Operator's requested **Tune Goal**; the **Tuning Agent** uses that response before creating a **Loop**.
- For `request_flight_capture` tasks, the Operator Console shows the capture goal, Pilot instructions, Operator post-flight reporting steps, and separate **Tuning Agent** follow-up steps. Diagnostic FC setup, **Post-flight Transfer**, and **Import** are the **Tuning Agent**'s responsibility through **FCS**/`tuna-core`; the Operator response is only `captured_needs_transfer` or `capture_failed`.
- For `review_tune_update` tasks, the Operator Console shows the **Diagnosis**, structured settings, and Betaflight CLI artifact.
- Approving a `review_tune_update` task requires a safety confirmation checkbox and changes the **Tune Update** to `approved_pending_write`.
- Rejecting a `review_tune_update` task requires an **Operator** reason and changes the **Tune Update** to `rejected`.
- The **Tuning Agent** observes `approved_pending_write`, performs write-back through **FCS**, then records `applied` or `write_failed`.

## Build setup

- The **Tuning Agent** should extract what it can from the FC through **FCS** to help establish the current **Build**.
- Useful extracted data includes FC/firmware identity, board/target details where available, and current tune snapshot.
- The **Operator** confirms whether the extracted data belongs to an existing **Build** or a new **Build**.

## Blackbox Log transfer and Import

- **Post-flight Transfer** means moving completed **Blackbox Logs** from FC storage to the **Host Computer** using FCS over either the **Bridge** or direct USB.
- The Tuning Agent-facing command for v1 **Post-flight Transfer** is `tuna-fcs blackbox transfer --connection bridge --bridge-host ... --output ... --json` for the **Bridge**, or `--connection usb --usb-device ...` for a direct USB FC on the **Host Computer**; afterward the Tuning Agent records the retained Host Computer artifact with `python3 -m tuna_core --db ... log import ... --json`.
- `tuna-fcs blackbox transfer` owns Bridge/FC mode validation, optional Betaflight `msc` triggering, waiting for MSC readiness, preferring the actual mounted Betaflight `.bbl` file when available, falling back to raw MSC download with resume sidecars, trimming leading padding before the Blackbox header for raw fallback, and validating that the output starts with `H Product:Blackbox`.
- When starting from USB CDC/MSP mode, `tuna-fcs blackbox transfer` discovers the FC-reported Blackbox storage `used_size` before triggering MSC mode. `--size` remains an override/debug option for cases such as resuming while the Bridge is already in MSC raw mode and MSP storage discovery is unavailable.
- After successful raw MSC transfer, the **Operator** must reset/power-cycle the FC back to USB CDC/MSP mode before further FC operations; current v1 cannot reliably return from MSC to CDC through FCS alone.
- MSP dataflash download is not a Tuna **Post-flight Transfer** fallback because it is too slow for the normal workflow. If raw MSC transfer is unavailable, the **Tuning Agent** should request FCS/Bridge remediation or report the hardware limitation.
- **Import** means registering a transferred **Blackbox Log** in Tuna state, associating it with a **Build**, making it analyzable, and extracting metadata.
- The **Tuning Agent** performs Import; the **Operator** does not have to manually import files as a normal workflow step.
- Import should attempt metadata extraction from the beginning.
- Import records source path, managed/canonical path, file size, hash, import time, **Build** association, parse status, metadata JSON, and warnings where available.

Validation note from 2026-06-06: a real FC **Blackbox Log** was transferred through `tuna-fcs blackbox transfer` from `tuna-bridge-usb` while the FC was in MSC raw mode, using `--size 868352` and `--chunk-size 262144`. The transfer downloaded `868352` raw bytes with one retry, trimmed the Blackbox header at raw offset `562176`, wrote a `306176` byte `.bbl`, and verified `download.starts_with_blackbox_header=true`. Tuna then imported it as **Blackbox Log** `log_id=2` with `parse_status=readable`, decoded it to `tuna-data/decoded-logs/log-2.csv`, and analyzed it as `analysis_id=3`. The analysis found `184` rows over `0.090817` seconds and marked the log unusable only because the capture duration was too short for tuning analysis. After transfer, the FC remained in MSC mode and required Operator reset/power-cycle before further USB CDC/MSP operations.

Follow-up validation on 2026-06-06 confirmed the one-shot CDC/MSP-to-MSC path: `tuna-fcs blackbox transfer` started from `USB_CDC_CONNECTED`, entered Betaflight CLI, sent `msc`, observed `msc_raw=1`, transferred the same `868352` raw bytes with zero retries, trimmed the header at raw offset `562176`, wrote a `306176` byte `.bbl`, and verified the Blackbox header.

Erase-after-import validation on 2026-06-06 confirmed `tuna-fcs blackbox erase --bridge-host tuna-bridge-usb --confirm erase-transferred-blackbox-log --json` after validated transfer/import. Storage changed from `used_size=868352` before erase to `used_size=0` on a follow-up storage probe, with `total_size=16777216` still reported.



## Blackbox Log analysis

- Do not implement a full Blackbox binary decoder in Tuna initially.
- Use Betaflight `blackbox_decode` as the first decoder backend for `.bbl` to CSV conversion.
- Treat Blackbox Explorer and PIDtoolbox as human reference/validation tools, not the first automated backend.
- `python3 -m tuna_core --db ... analysis decode --log-id ... --json` decodes an imported **Blackbox Log** to a CSV artifact and records it in SQLite.
- `python3 -m tuna_core --db ... analysis analyze --log-id ... --json` analyzes the latest decoded CSV, or a provided CSV path, and records JSON analysis in SQLite.
- `python3 -m tuna_core --db ... analysis decode-analyze --log-id ... --json` is the preferred **Tuning Agent** command because it avoids accidentally running decode and analyze in parallel.
- Initial analysis is intentionally simple and machine-readable: row count, duration, fields present, field count, ranges for gyro/setpoint/motor/PID-term fields, and warnings for missing expected fields.
- Future analysis can add maneuver detection, noise summaries, response/overshoot metrics, motor saturation checks, and PIDtoolbox-like spectral analysis.

## Tuning Agent write-back handoff

- The **Tuning Agent** finds Operator-approved writes with `tuna-core update pending-writes --json`.
- Pending write results include the **Tune Update** id, **Build** id, **Tuning Iteration** id, structured settings, Betaflight CLI artifact, and **Diagnosis** text where available.
- The **Tuning Agent** performs write-back through **FCS**, not through the Operator Console.
- FCS owns the low-level Betaflight CLI write-back helper exposed as `tuna-fcs cli write --json`.
- After write-back, the **Tuning Agent** records either `tuna-core update apply --update-id ... --json` or `tuna-core update record-write-failure --update-id ... --failure ... --json`.
- The initial FCS write-back boundary sends generated Betaflight CLI text over the raw Bridge transport after entering CLI mode. The caller owns safety checks and FC identity verification before invoking it.
- Hardware validation on 2026-06-06 confirmed `tuna-fcs cli write` against `tuna-bridge-usb` with a no-op approved-value CLI command, `set d_pitch = 46`, followed by `save`; the FC accepted the command and a post-write MSP smoke test reported Betaflight `25.12.3`, variant `BTFL`, MSP API `1.47`.

## Package structure

```text
tuna_core/                  Durable Tuna state, domain rules, SQLite storage, state services, and `tuna-core` CLI.
tuna_console/               Flask Operator Console and web templates; records Operator responses into tuna_core.
skills/tuna-agent/         Tuning Agent skill/instructions injected by the Operator Console supervisor.
tuna_fcs/                   Standalone FCS hardware CLI/package for Bridge or direct-USB FC operations.
tuna_blackbox/              Standalone Blackbox metadata, decode, analysis, and segment-row CLI/package.
tests/                      Unit tests for domain rules, storage, services, CLIs, web, FCS, and Blackbox analysis.
```

