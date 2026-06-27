# Tuna roadmap and status

This is the canonical project roadmap for currently implemented, partially
implemented, and remaining work. Detailed background stays in focused reference
docs:

- [`domain-model.md`](domain-model.md): canonical Tuna vocabulary and rules.
- [`tune-workflow-decisions.md`](tune-workflow-decisions.md): workflow and CLI/API decisions.
- [`pidtoolbox-analysis-todo.md`](pidtoolbox-analysis-todo.md): PIDtoolbox-inspired analysis background and implementation history.
- [`chirp-investigation.md`](chirp-investigation.md): CHIRP research and constraints.
- [`pi-tuning-agent-rpc.md`](pi-tuning-agent-rpc.md): Pi RPC **Tuning Agent** integration design.
- [`operator-console-ux.md`](operator-console-ux.md): Operator Console UX backlog.

## Verification snapshot

Last code/status check:

- `make quick` passed.
- `pytest tests/test_analysis*.py tests/test_tuna_blackbox_cli.py tests/test_pi_supervisor_web.py tests/test_operator_tasks_web.py` passed with 72 tests.

## Recommended next priorities

1. Validate analysis against more real **Blackbox Logs**, especially CHIRP and
   RPM/filter-debug captures.
2. Add FCS helpers for reading/writing diagnostic Blackbox logging settings.
3. Persist normalized Blackbox setting snapshots with imported **Blackbox Logs**.
4. Improve Operator Console review UX for **Tune Updates** and Loop progress.
5. Add a guarded Workbench no-hardware E2E seeding action.
6. Add CHIRP setup/capture workflow only after real-log validation.

## Analysis and Blackbox status

### Implemented

- Active-flight-only metrics through `active_analysis`.
- Clean high-rate segment summaries through `segment_gated_analysis`.
- Windowed frequency-vs-throttle heatmap while retaining the older heatmap.
- Filter attenuation analysis comparing filtered gyro with unfiltered gyro where
  fields are available.
- First-pass FFT/PSD summaries, noise peaks, and low/mid/high band energy.
- First-pass motor output, saturation, throttle-bin, and imbalance summaries.
- First-pass PID-term ranges, D-term noise/spikes, I-term windup proxies,
  feedforward activity, and P/D balance evidence.
- First-pass step-response metrics and per-axis response classifications.
- First-pass propwash/throttle-recovery analysis.
- Roll-focused cross-axis flip disturbance analysis.
- Evidence-only `tuning_evidence` with filter diagnosis, PID response
  classifications, and capture-plan recommendations.
- Compact `tuna-core analysis` and standalone `tuna-blackbox` evidence views:
  `filter-evidence`, `pid-response`, `noise-peaks`, `rpm-filter`, `propwash`,
  and `capture-plan`.
- Expanded before/after comparison, including `outcome_summary`.
- Decoded-CSV Blackbox header-setting extraction into `blackbox_settings` and
  `config_snapshot` when header rows are present.
- `chirp_analysis` for decoded CSV inputs with CHIRP debug-mode gating,
  setpoint/gyro/debug field checks, segment extraction, and first-pass frequency
  response metrics.

### Partially implemented

- RPM/dynamic-notch evidence: debug-mode family labeling and first-pass residual
  harmonic evidence exist, but full debug-mode-specific semantics remain TODO.
- Blackbox setting tracking: decoded CSV settings and generic `.bbl` metadata are
  captured, but imported **Blackbox Logs** do not yet have a normalized setting
  snapshot separate from metadata/analysis JSON.
- Maneuver detection: high-rate segments, throttle punches/chops, propwash, and
  roll-focused cross-axis flip evidence exist; snap flips, yaw spins,
  hover/cruise, broader cross-axis analysis, and crash/failsafe/RX-loss exclusion
  remain TODO.
- Before/after evaluation: compact analysis comparisons exist, but same-**Loop**
  pair selection and stronger linkage to applied **Tune Updates** remain TODO.

### Still TODO

- Validate thresholds/classifications against more real **Blackbox Logs** and
  compare outputs against Betaflight Configurator/PIDtoolbox.
- Add a real or trimmed CHIRP fixture with regression tests.
- Verify CHIRP high-resolution scaling and decoded header parsing against real
  `blackbox_decode` output.
- Generate static SVG/PNG Operator-review artifacts such as setpoint-vs-gyro
  overlays, spectrum plots, and throttle-frequency heatmaps.

## FCS and diagnostic logging status

### Implemented

- FCS `inspect` for identity/storage information.
- FCS **Post-flight Transfer** over Bridge or direct USB.
- FCS Blackbox erase after validated transfer/import.
- Generic FCS Betaflight CLI write-back through `tuna-fcs cli write`.
- Fake FCS mode for no-hardware exploratory workflow tests.
- **Operator Notifications** for diagnostic-only Blackbox/logging setting changes.

### Still TODO

- Dedicated FCS helpers for reading relevant Betaflight Blackbox settings.
- Dedicated FCS helpers for applying diagnostic Blackbox logging settings without
  treating them as flight-behavior **Tune Updates**.
- CHIRP diagnostic setup workflow, after real-log validation: verify firmware
  CHIRP support, set high-resolution Blackbox logging and `debug_mode = CHIRP`,
  record an **Operator Notification**, then create a CHIRP-specific
  `request_flight_capture` **Operator Task**. Do not trigger CHIRP automatically.

## Operator Console and Tuning Agent status

### Implemented

- Pi RPC **Tuning Agent** supervisor start/continue behavior.
- Per-**Loop** Pi session id/path, status, process fields, debug trace, and
  resume cursor storage.
- Abort action for a running **Tuning Agent** process.
- Continue/resume behavior that can reuse an idle running process or restart
  from a stored Pi session after interruption/abort.
- Workbench Tuning Agent status, live-event state, start/continue/abort controls,
  open **Operator Tasks**, open **Operator Notifications**, and recent durable
  Loop activity.
- Full `review_tune_update` task pages with **Diagnosis**, structured absolute
  target settings, generated Betaflight CLI artifact, and safety-confirmed
  approval/rejection forms.
- No-hardware workflow support through fake FCS mode, `analysis record-fixture`,
  and named fixture scenarios.

### Partially implemented

- Tune Update review summary: full task pages and activity target summaries
  exist, but the Workbench current task card does not yet show a first-class
  review summary with CLI and **Diagnosis** confidence inline.
- Agent transcript review: raw/supervisor trace exists, but not a summarized
  expert audit panel.
- No-hardware E2E: CLI/test fixtures exist, but not a guarded Workbench action
  that seeds the complete fixture-backed exploratory **Loop**.

### Still TODO

- Compact cyclic Loop status line:
  `Blackbox Log -> Diagnosis -> Review -> Write & Apply -> Result -> Next flight ↺`.
- First-class Workbench Tune Update summary for review tasks.
- Guarded Workbench expert action for fixture-backed no-hardware E2E setup.
- Expert transcript review panel summarizing commands, **Operator Tasks**,
  fixture usage, discouraged commands, and final outcome.
- Continued Pi RPC resume/restart hardening against real terminal/process
  failures.
