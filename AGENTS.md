# Agent Guide

## Repo orientation

Tuna is a drone-tuning system that iterates toward a better tune from recorded flight data. Keep the actor that analyzes tuning separate from the actor that flies the drone and the human operating Tuna.

## Domain vocabulary

Use these exact terms in issues, tests, code, plans, and summaries:

- **Tuning Agent**: AI agent that analyzes flight data and proposes tuning changes. Avoid: Agent.
- **Pilot**: human who flies the drone and performs maneuvers. Avoid: Operator, Agent.
- **Operator**: human who operates **Tuna** on the **Host Computer** and performs human-only workflow actions.
- **Host Computer**: machine that receives uploaded **Blackbox Logs** and runs **Tuna** first-version workflows.
- **Blackbox Log**: recorded flight log produced by the flight controller. Avoid: blackbox data, log file, recording.
- **Build**: specific physical drone setup relevant to tuning. Avoid: drone configuration, rig.
- **Tune Goal**: target tuning outcome for a specific **Build** and flying style. Avoid: perfect tune.
- **Loop**: larger tuning effort containing one or more **Tuning Iterations** for one **Build** and **Tune Goal**.
- **Tuning Iteration**: one pass from analysis of imported logs through no-change or applied/rejected **Tune Update**.
- **Diagnosis**: explanation of what the **Tuning Agent** found and why it recommends change or no change.
- **Tune Update**: absolute target values for flight-controller tuning config; may include PID/filter changes.
- **FC Bridge** / **Bridge**: firmware that provides Wi-Fi access from the **Host Computer** to flight-controller capabilities.
- **FC Service** / **FCS**: host-side service using the **Bridge** for higher-level flight-controller operations.
- **Post-flight Transfer**: transfer of completed **Blackbox Logs** after disarm; not live streaming.
- **Import**: bringing a transferred **Blackbox Log** into **Tuna**, associating it with the current **Build**, and making it analyzable.

## Domain rules

- A **Pilot** generates **Blackbox Logs**; an **Operator** runs Tuna workflows on the **Host Computer**.
- The **Tuning Agent** uses **FCS**, not raw Bridge/protocol access, for log operations and write-back.
- The **Bridge** may expose raw flight-controller protocol access, but **Post-flight Transfer** must preserve logs faithfully without semantic transformation.
- The **Host Computer** retains transferred log history; malformed/truncated/unreadable logs are retained as diagnostic artifacts until understood.
- In v1, the **Operator** sets the current **Build** before a **Loop** begins and decides whether physical/tuning-relevant changes create a new **Build**.
- A **Loop** has one fixed **Build** and one fixed **Tune Goal**; a **Build** may have multiple **Loops** over time.
- A **Loop** ends when the **Tuning Agent** concludes no further improvement should be made, or the **Operator** starts a new **Loop** for a different **Build** or **Tune Goal**.
- A **Loop** may exist before any **Tuning Iteration** starts and retains ordered history of applied/rejected updates and loop-end decisions.
- At most one **Tuning Iteration** may remain open in a **Loop** at a time.
- The **Tuning Agent** chooses which imported logs belong to a **Tuning Iteration** and may defer or reuse logs as reference input.
- Each successful **Tuning Iteration** produces exactly one **Diagnosis** and either a **Tune Update** or no change.
- A failed **Tuning Iteration** is distinct from a completed no-change result and remains in **Loop** history.
- A **Tune Update** applies to one **Build** and is expressed as absolute target values, not only deltas.
- Applying a **Tune Update** completes the **Tuning Iteration** and continues the same **Loop**.
- If later evidence is worse, start a new **Tuning Iteration** in the same **Loop**; do not reopen the previous one.
- If **Operator** review is enabled, the iteration remains open until the update is applied or rejected.
- Rejected updates do not change the current tune; v1 rejection requires an **Operator** reason and does not include manual editing.
- If application fails, the iteration remains incomplete with the failure recorded; retries may occur in the same open iteration.
- Current tune source of truth in v1 is Tuna's most recently applied recorded **Tune Update**, unless the **Operator** declares an out-of-band change.
- The **Tuning Agent** owns the decision to discard the FC copy of a transferred log; in v1 the **Operator** performs deletion.

