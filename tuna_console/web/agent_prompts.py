from __future__ import annotations

import importlib.resources
from pathlib import Path
from typing import Any


def initial_prompt(
    *,
    db_path: str | Path,
    loop: dict[str, Any],
    bridge_host: str,
    fc_connection: str,
    usb_device: str,
) -> str:
    bridge_line = bridge_host or "not provided"
    usb_line = usb_device or "auto-detect"
    connection_command = "python3 -m tuna_fcs.cli inspect --connection usb --json" if fc_connection == "usb" else "python3 -m tuna_fcs.cli inspect --connection bridge --json"
    fcs_step = f"2. Query the connected FC with `{connection_command}` and compare that snapshot with the Loop Build snapshot."
    return f"""Act as the Tuna Tuning Agent for this Loop. Use the injected operating instructions below; do not load skills, context files, source files, or repository documentation during normal Loop operation.

Injected Tuna Tuning Agent operating instructions:
{_tuning_agent_skill_text()}

Runtime Loop assignment:

Operator requested work on an existing Loop.

Database: {db_path}
Loop: {loop['id']}
Build: {loop['build_id']} ({loop['build_name']})
Tune Goal: {loop['tune_goal']}
FCS connection: {fc_connection}
FCS Bridge host: {bridge_line}
USB FC device: {usb_line}

First:
1. Inspect compact Tuna state with `python3 -m tuna_core loop status --loop-id {loop['id']} --json`.
{fcs_step}
3. If FCS inspection fails, create a `request_fcs_connection` Operator Task. Only create a `confirm_build` Operator Task when a real FCS-derived FC snapshot is available and is missing, ambiguous, or does not clearly match the Loop Build. When creating a Build confirmation task for this Loop, include `--loop-id {loop['id']}` and stop for Operator confirmation before starting a Tuning Iteration or proposing a Tune Update.
4. Confirm whether the Build and Tune Goal are sufficient.
5. If needed, create Operator Tasks.
6. If `loop status` shows usable imported Blackbox Logs, no current Tuning Iteration, and no open Operator Task, select the best suitable log and start a Tuning Iteration.
7. Create or resume the Loop context in this Pi session.
8. Do not start a Tuning Iteration until suitable imported Blackbox Logs are selected.

Preserve Tuna safety rules. Do not apply a Tune Update without Operator review.
Use FCS, not raw Bridge protocol access, for flight-controller operations.
Use CLI help only if a documented command fails or syntax is not provided here; do not read source code or repository docs during normal Loop operation.
There is no `update list` command; use `python3 -m tuna_core update pending-writes --json` for approved writes and `loop status` or `loop context` for current Loop state.
If Tuna state explicitly marks FCS data or Blackbox Analysis as fixture-sourced for no-hardware exploratory testing, and the analysis is usable with no more capture data needed, treat that fixture evidence as sufficient to exercise the Tune Update review/write-back workflow. Do not choose no-change solely because the evidence is fixture-sourced.
"""


def continue_prompt(
    *,
    db_path: str | Path,
    loop: dict[str, Any],
    bridge_host: str,
    fc_connection: str,
    usb_device: str,
) -> str:
    bridge_line = bridge_host or "not provided"
    usb_line = usb_device or "auto-detect"
    return f"""Continue acting as the Tuna Tuning Agent for this existing Loop after an interruption or abort. Use the injected operating instructions below; do not load skills, context files, source files, or repository documentation during normal Loop operation.

Injected Tuna Tuning Agent operating instructions:
{_tuning_agent_skill_text()}

Runtime Loop assignment:

Database: {db_path}
Loop: {loop['id']}
Build: {loop['build_id']} ({loop['build_name']})
Tune Goal: {loop['tune_goal']}
FCS connection: {fc_connection}
FCS Bridge host: {bridge_line}
USB FC device: {usb_line}

First:
1. Inspect compact Tuna state with `python3 -m tuna_core loop status --loop-id {loop['id']} --json`.
2. Check open and recently resolved Operator Tasks and Operator Notifications. If this continuation followed an Operator Task resolution, read that task with `task show --task-id <id> --json`.
3. Resume the Loop decision process from durable Tuna state and the existing Pi session history.
4. If a previous action was interrupted, verify state before retrying it.
5. If `loop status` or `update pending-writes --json` shows approved pending writes, use `python3 -m tuna_core update pending-writes --json`, write through FCS with `python3 -m tuna_fcs.cli cli write ... --confirm write-fc-cli --json`, then record success with `python3 -m tuna_core update apply --update-id <id> --json`. Do not run `--help` for these standard commands unless a command fails.
6. If there is no current Tuning Iteration, no pending write, no open Operator Task, and `loop status` shows usable imported Blackbox Logs, select a suitable log and start a new Tuning Iteration instead of waiting for another Operator action.
7. If you create a `confirm_build` Operator Task, include `--loop-id {loop['id']}` and wait for the Operator response before starting a Tuning Iteration or proposing a Tune Update.

Preserve Tuna safety rules. Do not apply a Tune Update without Operator review.
Use FCS, not raw Bridge protocol access, for flight-controller operations.
Use CLI help only if a documented command fails or syntax is not provided here; do not read source code or repository docs during normal Loop operation.
There is no `update list` command; use `python3 -m tuna_core update pending-writes --json` for approved writes and `loop status` or `loop context` for current Loop state.
If Tuna state explicitly marks FCS data or Blackbox Analysis as fixture-sourced for no-hardware exploratory testing, and the analysis is usable with no more capture data needed, treat that fixture evidence as sufficient to exercise the Tune Update review/write-back workflow. Do not choose no-change solely because the evidence is fixture-sourced.
"""


def _tuning_agent_skill_text() -> str:
    return importlib.resources.files("skills").joinpath("tuna-agent/SKILL.md").read_text(encoding="utf-8").strip()
