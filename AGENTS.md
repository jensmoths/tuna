# Agent Guide

## Purpose

This repo contains **Tuna**, a drone-tuning system. The `tune` Python package/CLI
is only the durable state, domain-rules, parsing, and helper-tool layer used by
the **Tuning Agent**. Do not treat `tune` as the whole Tuna product or as the
workflow brain.

## Read before changing behavior

- `docs/domain-model.md` — canonical Tuna vocabulary, actors, and domain rules.
- `docs/tune-workflow-decisions.md` — recorded workflow and implementation decisions.
- `tune/agent/SKILL.md` — operating procedure when acting as the **Tuning Agent**.
- `fcs-host/README.md` — host-side **FCS** / **Bridge** tooling.
- Relevant tests under `tests/`.

## Required vocabulary

Use the canonical terms from `docs/domain-model.md` in code, tests, docs, plans,
and summaries. In particular, preserve distinctions between **Tuning Agent**,
**Pilot**, **Operator**, **Host Computer**, **Blackbox Log**, **Build**, **Tune
Goal**, **Loop**, **Tuning Iteration**, **Diagnosis**, **Tune Update**, **FCS**,
**Bridge**, **Post-flight Transfer**, **Import**, and **Operator Task**.

Avoid looser substitutes such as “Agent”, “log file”, “drone configuration”, or
“perfect tune” when a domain term applies.

## Architecture rules

- The **Tuning Agent** owns Tuna workflow decisions.
- `tune` records/queries durable state and enforces domain rules; it must not
  decide what action happens next in a **Loop**.
- The **Tuning Agent** uses **FCS**, not raw **Bridge** protocol access, for
  flight-controller operations and write-back.
- The Operator Console records **Operator Task** responses and approvals; it
  must not perform flight-controller write-back itself.
- **Tune Updates** are absolute target settings, not deltas.
- Retain malformed, truncated, unsupported, and unreadable **Blackbox Logs** as
  diagnostic artifacts.

## Development

Prefer focused, tested changes. Useful commands:

```bash
pytest
pytest tests/test_tune_workflow.py
pytest tests/test_tune_cli.py
```

Use JSON output for CLI behavior intended for the **Tuning Agent**.

## Safety

Do not erase flight-controller **Blackbox Log** copies unless transfer
validation, **Host Computer** retention, and **Import** have succeeded.

Do not add automatic flight-controller write-back paths that bypass
**Operator** review.
