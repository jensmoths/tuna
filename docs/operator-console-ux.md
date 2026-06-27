# Operator Console UX backlog

These are larger Workbench and workflow ideas that look promising from real
no-hardware E2E testing, but need Operator confirmation before implementation.
The canonical cross-project roadmap is [`roadmap.md`](roadmap.md); this file
keeps UX-specific detail.

## Current implementation notes

- The Workbench already shows **Tuning Agent** status, live-event state,
  start/continue controls, abort controls, recent durable Loop activity, open
  **Operator Tasks**, open **Operator Notifications**, and concise Tune Update
  target summaries in the activity feed.
- Full `review_tune_update` task pages already show the **Diagnosis**,
  structured absolute target settings, generated Betaflight CLI artifact, and
  the safety-confirmed approval/rejection forms.
- Pi RPC supervisor trace is already stored and displayed for debugging, but it
  is still a raw/supervisor trace rather than a summarized transcript review.
- No-hardware exploratory support exists through fake FCS mode and
  `analysis record-fixture`, but seeding a complete fixture-backed exploratory
  **Loop** still requires CLI/test setup rather than one guarded Workbench action.

## Compact Loop status line

Turn the Workbench into a compact one-line Loop status graphic. A full circle is
too space-hungry for the Operator Console, but the line should still indicate
that the workflow repeats. Build should stay in Loop context because it is
established once; the status line should only show the repeating Loop cycle:

```text
Blackbox Log -> Diagnosis -> Review -> Write & Apply -> Result -> Next flight ↺
```

The current step can use a strong marker, completed steps can use check marks,
and future steps can stay muted. The `↺` on the final step communicates that the
Loop can continue with another flight/Blackbox Log without needing a circular
layout.

For normal Operator-facing UX, collapse write-back and Tuna state recording into
one step: **Write & Apply**. Internally these are distinct:

- **Write**: the Tuning Agent sends the approved CLI settings to the FC through
  FCS.
- **Apply**: Tuna records that the write succeeded and marks the Tune Update as
  applied.

Only split them visually when the write is in progress, fails, or needs
diagnostic detail.

Why it may help: the activity feed is clearer now, but it is still historical.
A compact Loop status line would make the cyclic state machine legible at a
glance without implying Build confirmation repeats every iteration.

Status: still an Operator Console UX TODO. The current Workbench has status
cards and an activity feed, but not this cyclic one-line Loop progress graphic.

## Tune Update review summary

Make the review task show a first-class Tune Update summary directly in the
Workbench: intended target settings, generated CLI, Diagnosis confidence, and
why unchanged settings are not shown. Keep the full task detail link for raw
payloads.

Why it may help: the Operator should not have to open the full task page or infer
from activity text to understand exactly what will be written.

Status: partially implemented. The full task page shows the needed review data,
and activity entries summarize target settings, but the Workbench current task
card does not yet show a first-class Tune Update summary with CLI and Diagnosis
confidence inline.

## Built-in no-hardware E2E mode

Add an explicit Workbench expert action for creating a fixture-backed exploratory
Loop: create/import a known reference Blackbox Log, record a named fixture
analysis, set fake FCS mode, and start the Tuning Agent. This should be clearly
marked as test-only and must not bypass Operator approval or FCS write-back
boundaries.

Why it may help: current E2E testing still needs CLI fixture seeding between
browser steps. A guarded test mode would make exploratory testing faster and
more repeatable.

Status: partially implemented. Fake FCS and `analysis record-fixture` support
exist, with no-hardware E2E tests, but there is not yet a guarded Workbench
expert action that seeds the complete fixture-backed Loop.

## Agent transcript review panel

Add an expert-only transcript review panel that summarizes the last Tuning Agent
run: commands used, Operator Tasks created, whether it used fixtures, whether it
used discouraged commands, and final outcome.

Why it may help: after E2E runs, we currently inspect server logs manually to
find confusion or inefficiency. A structured review panel would make this audit
part of the product workflow.

Status: partially implemented. Supervisor/debug trace capture and display exist,
including tool/status events, but this idea still needs a summarized audit panel
that extracts commands used, fixture use, discouraged commands, tasks created,
and final outcome.
