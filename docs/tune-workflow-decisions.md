# Tune workflow decisions

Decisions recorded before implementing the Tuna workflow model.

## Naming and boundaries

- **Tuna** is the whole drone-tuning system/product.
- `tune` is the Python package and helper CLI used by the **Tuning Agent**.
- `tune` owns durable state, SQLite persistence, domain rules, deterministic helpers, and Blackbox Log metadata extraction.
- `tune` is not the workflow brain and should not decide what happens next in a **Loop**.
- The **Tuning Agent** owns workflow decisions and may use `tune`, FCS, and Pi skills.
- The **Operator** performs human-only actions and review decisions.
- The **Pilot** flies and generates **Blackbox Logs**.

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
- Keep the UI plain black and white; prioritize clear review UX over visual styling.
- The Operator Console shows dashboard state, **Operator Tasks**, **Tune Updates**, and imported **Blackbox Logs**.
- **Operator Tasks** are durable structured requests from the **Tuning Agent** to the **Operator**.
- **Operator Tasks** are not free-form chat; they are review/confirmation/action cards with structured payloads and responses.
- The **Tuning Agent** creates **Operator Tasks** when it needs human input.
- The Operator Console records **Operator Task** responses into `tune` state.
- For `review_tune_update` tasks, the Operator Console shows the **Diagnosis**, structured settings, and Betaflight CLI artifact.
- Approving a `review_tune_update` task requires a safety confirmation checkbox and changes the **Tune Update** to `approved_pending_write`.
- Rejecting a `review_tune_update` task requires an **Operator** reason and changes the **Tune Update** to `rejected`.
- The **Tuning Agent** observes `approved_pending_write`, performs write-back through **FCS**, then records `applied` or `write_failed`.

## Build setup

- The **Tuning Agent** should extract what it can from the FC through **FCS** to help establish the current **Build**.
- Useful extracted data includes FC/firmware identity, board/target details where available, and current tune snapshot.
- The **Operator** confirms whether the extracted data belongs to an existing **Build** or a new **Build**.

## Blackbox Log transfer and Import

- **Post-flight Transfer** means moving completed **Blackbox Logs** from FC/Bridge storage to the **Host Computer** using FCS.
- **Import** means registering a transferred **Blackbox Log** in Tuna state, associating it with a **Build**, making it analyzable, and extracting metadata.
- The **Tuning Agent** performs Import; the **Operator** does not have to manually import files as a normal workflow step.
- Import should attempt metadata extraction from the beginning.
- Import records source path, managed/canonical path, file size, hash, import time, **Build** association, parse status, metadata JSON, and warnings where available.

## Proposed package structure

```text
tune/                       Python package for durable Tuna state, rules, and deterministic helpers.
  __init__.py               Package marker and public version/export surface.
  domain/                   Pure domain objects and rules; no SQLite, no CLI, no FCS sockets.
    __init__.py             Domain package exports.
    models.py               Dataclasses/enums for Build, Loop, Tuning Iteration, Diagnosis, Tune Update, Blackbox Log.
    rules.py                Rule checks like one open Tuning Iteration per Loop and required Operator rejection reason.
  storage/                  SQLite persistence layer for Tune records.
    __init__.py             Storage package exports.
    sqlite.py               Connection handling, schema creation, transactions, row mapping.
    migrations.py           Versioned schema migration runner.
    schema.sql              Initial SQLite schema for Builds, Loops, logs, iterations, diagnoses, updates.
  services/                 Application services used by agent tools; enforces domain rules through storage.
    __init__.py             Service package exports.
    builds.py               Create/select Builds, store FC-derived snapshots, record Operator notes.
    loops.py                Create/end Loops for one Build and one Tune Goal.
    logs.py                 Import Blackbox Logs, hash/copy files, call metadata extraction, deduplicate.
    iterations.py           Create/fail/complete Tuning Iterations and attach selected imported logs.
    diagnoses.py            Record the Tuning Agent's Diagnosis for a Tuning Iteration.
    tune_updates.py         Propose/apply/reject Tune Updates with structured settings and generated CLI text.
  blackbox/                 Blackbox Log parsing and metadata extraction.
    __init__.py             Blackbox package exports.
    parser.py               Reads `.bbl` files and extracts available metadata.
    metadata.py             Metadata dataclasses/normalization for firmware, PIDs, rates, filters, fields, warnings.
  cli/                      Thin helper CLI used by the Tuning Agent; does not own workflow decisions.
    __init__.py             CLI package marker.
    main.py                 Command dispatcher for the `tune` executable.
  agent/                    Optional Pi skill/instructions for the Tuna Tuning Agent.
    SKILL.md                Agent procedure: use FCS and `tune`, own Loop decisions, produce Diagnosis/Tune Updates.
tests/                      Unit tests for Tune domain rules, storage, services, parser, and CLI command behavior.
```

