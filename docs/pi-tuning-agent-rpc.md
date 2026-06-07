# Pi RPC Tuning Agent integration

This document records the v1 design for running Pi as the Tuna **Tuning Agent**
from the local web **Operator Console**.

See `docs/domain-model.md` for canonical Tuna vocabulary and domain rules.

## Decisions

- Use one persistent Pi session per **Loop**.
- The web **Operator Console** process owns the Pi RPC supervisor.
- The **Operator Console** shows status only by default, not the full Pi
  transcript or raw tool stream.
- v1 uses Pi's normal tools to run `tune --json` commands for Tuna state and `fcs --json` commands for FC/Bridge hardware.
- v1 allows read/write operation from the start, while preserving the existing
  **Operator** review gate for every **Tune Update**.

## Responsibilities

### Skill

`tune/agent/SKILL.md` is the **Tuning Agent** job description and operating
procedure. It owns instructions for:

- Tuna vocabulary and domain rules.
- Safe **Tuning Agent** behavior.
- Use of `tune` for durable state and domain-rule enforcement.
- Use of **FCS** for flight-controller operations.
- When to create or resume a **Loop**.
- When to start a **Tuning Iteration**.
- Which imported **Blackbox Logs** to use as evidence.
- How to record a **Diagnosis**.
- When to propose a **Tune Update** or recommend no change.
- When to create **Operator Tasks** and **Operator Notifications**.

At runtime, the supervisor starts Pi with `--no-context-files` and
`--no-skills`, then injects the contents of `tune/agent/SKILL.md` into the
prompt. This gives the **Tuning Agent** the Tuna operating procedure without
loading repository context files or global/project skills.

The skill must not describe Pi RPC framing, Flask routes, subprocess restart
policy, or UI transport details.

### Supervisor

The Pi RPC supervisor is process and UI glue inside the **Operator Console**. It
owns:

- Starting `pi --mode rpc` for a **Loop**.
- Resuming the stored Pi session for a **Loop**.
- Sending initial prompts, steering messages, and follow-up messages.
- Reading JSONL responses/events from Pi.
- Tracking coarse Tuning Agent status for the **Operator Console**.
- Aborting a running Pi process when requested by the **Operator**.
- Keeping the Pi process in the Tuna working directory.
- Supplying runtime paths and context such as the Tuna database path and FCS
  Bridge host.

The supervisor must not become the workflow brain. It should not decide which
**Blackbox Logs** belong to a **Tuning Iteration**, whether a **Tune Update** is
needed, or what tuning values to propose.

### `tune`

`tune` remains the durable state, domain-rules, parsing, and helper-tool layer.
It records **Builds**, **Loops**, imported **Blackbox Logs**, **Tuning
Iterations**, **Diagnoses**, **Tune Updates**, **Operator Tasks**, and
**Operator Notifications**. It must not decide what action happens next in a
**Loop**.

### FCS

**FCS** remains the flight-controller operation boundary. The **Tuning Agent**
uses FCS for **Post-flight Transfer**, diagnostic Blackbox/logging configuration
changes, erasing transferred FC **Blackbox Log** copies after validation and
**Import**, and approved **Tune Update** write-back.

The **Operator Console** must not write to the flight controller directly.

## Session mapping

Each **Loop** has at most one active Pi session association:

```text
Loop id
  -> Pi session id
  -> Pi session file path
  -> supervisor status
```

The association may initially live in Operator Console-owned state. If it needs
to survive outside the web process reliably, add durable Tuna storage for it in a
focused migration.

When the **Operator** resumes a **Loop**, the supervisor should resume the stored
Pi session instead of starting a fresh one. A new Pi session should only be used
when the prior session is missing, corrupt, intentionally abandoned, or the
**Operator** starts a different **Loop**.

## Starting a Loop

The **Operator Console** collects:

- **Build** candidate or confirmed **Build** id.
- **Tune Goal**.
- FCS Bridge host when flight-controller operations are expected.
- Optional **Operator** notes.

Then the supervisor starts or resumes Pi RPC and sends an initial prompt.

Example initial prompt shape:

```text
Act as the Tuna Tuning Agent for this Loop. Use the injected operating
instructions below; do not load skills, context files, source files, or
repository documentation during normal Loop operation.

Injected Tuna Tuning Agent operating instructions:
<contents of tune/agent/SKILL.md injected by supervisor>

Runtime Loop assignment:

Operator requested a Loop.

Database: tune.sqlite3
Requested Build: 3
Tune Goal: reduce propwash while preserving freestyle response
FCS Bridge host: tuna-bridge-usb

First:
1. Inspect Tuna state with `python3 -m tune --db tune.sqlite3 loop context --loop-id <id> --json` when a Loop exists, or concise JSON tune commands otherwise.
2. Confirm whether the Build and Tune Goal are sufficient.
3. If needed, create Operator Tasks.
4. If sufficient, create or resume the Loop.
5. Do not start a Tuning Iteration until suitable imported Blackbox Logs are
   selected.

Preserve Tuna safety rules. Do not apply a Tune Update without Operator review.
Use FCS, not raw Bridge protocol access, for flight-controller operations.
Do not read source code during normal Loop operation; use CLI help if syntax is unclear.
```

The prompt gives context; it does not prescribe the full workflow outcome. The
**Tuning Agent** decides next steps using the skill, `tune`, and FCS.

## Status-only Operator Console

The **Operator Console** should show concise status labels derived from Pi RPC
events and known prompts. Suggested labels:

- `Starting Tuning Agent`
- `Inspecting Tuna state`
- `Confirming Build`
- `Creating or resuming Loop`
- `Waiting for Operator Task`
- `Waiting for Blackbox Logs`
- `Transferring Blackbox Log`
- `Importing Blackbox Log`
- `Decoding Blackbox Log`
- `Analyzing Blackbox Log`
- `Recording Diagnosis`
- `Tune Update awaiting Operator review`
- `Writing approved Tune Update through FCS`
- `Idle`
- `Aborted`
- `Failed`

The full Pi session remains available in Pi's session file for debugging or
audit, but the **Operator Console** should not make the transcript the normal
workflow UI.

## RPC commands used by the supervisor

The supervisor should start Pi with RPC mode:

```bash
pi --mode rpc --name "Tuna Loop <loop-id>"
```

Common commands:

```json
{"type":"prompt","message":"..."}
{"type":"steer","message":"..."}
{"type":"follow_up","message":"..."}
{"type":"abort"}
{"type":"get_state"}
{"type":"set_session_name","name":"Tuna Loop 12"}
```

If Pi is already streaming, the supervisor must use `steer`, `follow_up`, or a
`prompt` command with explicit streaming behavior. The supervisor should treat
`agent_end` as the transition to idle.

## Safety gates

Read/write operation is allowed in v1, but these gates are mandatory:

- **Tune Updates** require **Operator** review before write-back.
- Approval in the **Operator Console** means approved for **Tuning Agent**
  write-back through **FCS**, not already applied.
- The **Operator Console** does not perform flight-controller write-back.
- The **Tuning Agent** records successful write-back with `tune update apply` or
  records failure with `tune update record-write-failure`.
- The **Tuning Agent** must not erase FC **Blackbox Log** copies until transfer
  validation, **Host Computer** retention, and **Import** have succeeded.
- Diagnostic-only Blackbox/logging configuration changes made through **FCS**
  must be recorded as **Operator Notifications**.

## v1 implementation outline

1. Add Operator Console supervisor code that can launch `pi --mode rpc` in the
   Tuna working directory.
2. Store the Pi session id/path for each **Loop**.
3. Add a **Loop** action that sends the initial prompt for that **Loop**.
4. Track status from Pi RPC events and expose it on the **Loop** detail page.
5. Add an abort action for a running **Tuning Agent** process.
6. Add resume behavior that reconnects a **Loop** to its stored Pi session.

Keep this implementation focused. Do not add automatic workflow decisions to the
supervisor.

