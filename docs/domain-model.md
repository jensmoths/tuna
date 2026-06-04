# Tuna domain model

This document is the canonical vocabulary and domain-rule reference for Tuna.
Use these terms in issues, tests, code, plans, and summaries.

## Repo orientation

**Tuna** is the whole product/system, including the **Tuning Agent**,
state/history, Blackbox Log handling, FCS integration, and future user
interfaces. The `tune` Python package/CLI is only the durable state,
domain-rules, parsing, and helper-tool layer used by the **Tuning Agent**; do
not treat `tune` as the whole Tuna product.

## Domain vocabulary

- **Tuning Agent**: AI agent that analyzes flight data and proposes tuning
  changes. Avoid: Agent.
- **Pilot**: human who flies the drone and performs maneuvers. Avoid: Operator,
  Agent.
- **Operator**: human who operates **Tuna** on the **Host Computer** and performs
  human-only workflow actions.
- **Host Computer**: machine that receives uploaded **Blackbox Logs** and runs
  **Tuna** first-version workflows.
- **Blackbox Log**: recorded flight log produced by the flight controller.
  Avoid: blackbox data, log file, recording.
- **Build**: specific physical drone setup relevant to tuning. Avoid: drone
  configuration, rig.
- **Tune Goal**: target tuning outcome for a specific **Build** and flying style.
  Avoid: perfect tune.
- **Loop**: larger tuning effort containing one or more **Tuning Iterations** for
  one **Build** and **Tune Goal**.
- **Tuning Iteration**: one pass from analysis of imported logs through no-change
  or applied/rejected **Tune Update**.
- **Diagnosis**: explanation of what the **Tuning Agent** found and why it
  recommends change or no change.
- **Tune Update**: absolute target values for flight-controller tuning config;
  may include PID/filter changes.
- **FC Bridge** / **Bridge**: firmware that provides Wi-Fi access from the
  **Host Computer** to flight-controller capabilities.
- **FC Service** / **FCS**: host-side service using the **Bridge** for
  higher-level flight-controller operations.
- **Post-flight Transfer**: transfer of completed **Blackbox Logs** after disarm;
  not live streaming.
- **Import**: bringing a transferred **Blackbox Log** into **Tuna**, associating
  it with the current **Build**, and making it analyzable.
- **Operator Task**: durable structured request from the **Tuning Agent** to the
  **Operator** for human input, confirmation, or review. Avoid treating it as
  free-form chat. Examples include `confirm_build`, `request_tune_goal`,
  `request_flight_capture`, and `review_tune_update`.
- **Operator Notification**: durable informational record for the **Operator** when
  the **Tuning Agent** has made a diagnostic-only change, such as a
  Blackbox/logging setting change through **FCS**. It is not an **Operator Task**
  and only needs acknowledgement, not approval.
- `tune`: Python package and helper CLI for Tuna state, domain rules,
  deterministic Blackbox Log metadata extraction, and SQLite persistence. It is
  a tool used by the **Tuning Agent**, not the workflow brain.

## Domain rules

- A **Pilot** generates **Blackbox Logs**; the **Tuning Agent** owns Tuna
  workflow decisions; an **Operator** performs human-only workflow actions on
  the **Host Computer**.
- The **Tuning Agent** uses **FCS**, not raw Bridge/protocol access, for log
  operations and write-back.
- The **Tuning Agent** may use `tune` to query/record state, but `tune` must not
  decide what action should happen next in a **Loop**.
- The **Bridge** may expose raw flight-controller protocol access, but
  **Post-flight Transfer** must preserve logs faithfully without semantic
  transformation.
- The **Host Computer** retains transferred log history; malformed, truncated,
  unsupported, and unreadable logs are retained as diagnostic artifacts until
  understood.
- In v1, the **Operator** confirms the current **Build** before a **Loop** begins
  and decides whether physical/tuning-relevant changes create a new **Build**.
  The **Tuning Agent** should extract what it can from the FC through **FCS** to
  help this decision, then create a `confirm_build` **Operator Task** when human
  confirmation is needed.
- A **Loop** has one fixed **Build** and one fixed **Tune Goal**; a **Build** may
  have multiple **Loops** over time.
- When a **Tune Goal** is not clear, the **Tuning Agent** should create a
  `request_tune_goal` **Operator Task** and use the response before creating the
  **Loop**.
- A **Loop** ends when the **Tuning Agent** concludes no further improvement
  should be made, or the **Operator** starts a new **Loop** for a different
  **Build** or **Tune Goal**.
- A **Loop** may exist before any **Tuning Iteration** starts and retains ordered
  history of applied/rejected updates and loop-end decisions.
- At most one **Tuning Iteration** may remain open in a **Loop** at a time.
- The **Tuning Agent** chooses which imported logs belong to a **Tuning
  Iteration** and may defer or reuse logs as reference input.
- Each successful **Tuning Iteration** produces exactly one **Diagnosis** and
  either a **Tune Update** or no change.
- A failed **Tuning Iteration** is distinct from a completed no-change result and
  remains in **Loop** history.
- A **Tune Update** applies to one **Build** and is expressed as absolute target
  values, not only deltas.
- A **Tune Update** stores structured absolute target settings as the source of
  truth and may also store generated Betaflight CLI text as an application
  artifact.
- Applying a **Tune Update** completes the **Tuning Iteration** and continues the
  same **Loop**.
- If later evidence is worse, start a new **Tuning Iteration** in the same
  **Loop**; do not reopen the previous one.
- In v1, **Operator** review is required for every **Tune Update**; the iteration
  remains open until the update is applied or rejected.
- Rejected updates do not change the current tune; v1 rejection requires an
  **Operator** reason and does not include manual editing.
- If application fails, the iteration remains incomplete with the failure
  recorded; retries may occur in the same open iteration.
- The local web Operator Console records **Operator Task** responses and
  approval/rejection decisions; it must not perform FC write-back itself.
- Diagnostic-only Blackbox/logging configuration changes made by the **Tuning
  Agent** through **FCS** do not require **Operator** approval, but must be
  recorded as an **Operator Notification** with the reason and changed settings.
- When the **Tuning Agent** needs another **Blackbox Log**, it should create a
  `request_flight_capture` **Operator Task**. Any diagnostic FC setup needed for
  that capture remains the **Tuning Agent**'s responsibility through **FCS** and
  should be recorded separately as an **Operator Notification**.
- Approval of a **Tune Update** through the Operator Console means approved for
  **Tuning Agent** write-back through **FCS**, not already applied.
- Current tune source of truth in v1 is Tuna's most recently applied recorded
  **Tune Update**, unless the **Operator** declares an out-of-band change.
- After a successful **Post-flight Transfer** has been validated on the **Host
  Computer**, the **Tuning Agent** should erase the transferred **Blackbox Log**
  copy from the flight controller through **FCS**. Do not erase the FC copy if
  transfer validation, host-side retention, or **Import** fails.
- The **Tuning Agent** performs **Import** of transferred **Blackbox Logs** into
  Tuna state. Import must attempt metadata extraction from the beginning and
  retain parse status/warnings.
