# Agent Guide

- Tuna is a drone-tuning system; `tune` is only durable state, domain rules,
  parsing, and helper tooling for the **Tuning Agent**. Do not make it the
  workflow brain.
- Before behavior changes, read `docs/domain-model.md`,
  `docs/tune-workflow-decisions.md`, relevant tests, and `tune/agent/SKILL.md`
  when acting as the **Tuning Agent**.
- Use canonical Tuna terms from `docs/domain-model.md` in code, tests, docs,
  plans, and summaries; avoid loose substitutes like “Agent”, “log file”, or
  “drone configuration” when a domain term applies.
- The **Tuning Agent** owns Loop decisions; `tune` records/queries state and
  enforces domain rules, but must not decide the next Loop action.
- Use **FCS** for flight-controller operations; do not bypass it with raw
  **Bridge** protocol access. See `fcs-host/README.md`.
- The Operator Console records **Operator Task** responses and approvals; it
  must not perform flight-controller write-back.
- **Tune Updates** are absolute target settings, not deltas.
- Retain malformed, truncated, unsupported, and unreadable **Blackbox Logs** as
  diagnostic artifacts.
- Do not erase flight-controller **Blackbox Log** copies unless transfer
  validation, **Host Computer** retention, and **Import** have succeeded.
- Do not add automatic flight-controller write-back paths that bypass
  **Operator** review.
- Use JSON output for CLI behavior intended for the **Tuning Agent**.
- Useful checks: `pytest`, `pytest tests/test_tune_workflow.py`,
  `pytest tests/test_tune_cli.py`.
