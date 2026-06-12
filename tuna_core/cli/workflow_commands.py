from __future__ import annotations

import json
from typing import Any

from tuna_core.cli.output import emit, emit_command_error, print_json, row_to_dict
from tuna_core.services.diagnoses import record_diagnosis
from tuna_core.services.iterations import complete_no_change, complete_no_change_with_diagnosis, create_iteration
from tuna_core.services.tune_updates import approve_for_write, mark_applied, propose_tune_update, reject, record_application_failure


def handle_workflow_command(conn: Any, args: Any) -> int | None:
    for handler in (_handle_iteration_command, _handle_diagnosis_command, _handle_update_command):
        handled = handler(conn, args)
        if handled is not None:
            return handled
    return None


def _handle_iteration_command(conn: Any, args: Any) -> int | None:
    if args.area == "iteration" and args.action == "create":
        iteration_id = create_iteration(conn, args.loop_id, args.log_id)
        emit({"iteration_id": iteration_id}, args.json)
    elif args.area == "iteration" and args.action == "current":
        row = conn.execute("SELECT * FROM tuning_iterations WHERE loop_id = ? AND status = 'open'", (args.loop_id,)).fetchone()
        print_json(row_to_dict(row))
    elif args.area == "iteration" and args.action == "complete-no-change":
        try:
            complete_no_change(conn, args.iteration_id, args.reason)
        except ValueError as exc:
            emit_command_error(exc, args.json)
            return 1
        row = conn.execute("SELECT * FROM tuning_iterations WHERE id = ?", (args.iteration_id,)).fetchone()
        print_json(row_to_dict(row) if args.json else {"iteration_id": args.iteration_id})
    elif args.area == "iteration" and args.action == "complete-with-diagnosis":
        try:
            diagnosis_id = complete_no_change_with_diagnosis(conn, args.iteration_id, body=args.body, reason=args.reason, confidence=args.confidence, evidence=json.loads(args.evidence_json))
        except (json.JSONDecodeError, ValueError) as exc:
            emit_command_error(exc, args.json)
            return 1
        row = conn.execute("SELECT * FROM tuning_iterations WHERE id = ?", (args.iteration_id,)).fetchone()
        payload = row_to_dict(row)
        payload["diagnosis_id"] = diagnosis_id
        print_json(payload)
    else:
        return None
    return 0


def _handle_diagnosis_command(conn: Any, args: Any) -> int | None:
    if args.area == "diagnosis" and args.action == "record":
        try:
            diagnosis_id = record_diagnosis(conn, args.iteration_id, args.body, confidence=args.confidence, evidence=json.loads(args.evidence_json))
        except (json.JSONDecodeError, ValueError) as exc:
            emit_command_error(exc, args.json)
            return 1
        emit({"diagnosis_id": diagnosis_id}, args.json)
    else:
        return None
    return 0


def _handle_update_command(conn: Any, args: Any) -> int | None:
    if args.area != "update":
        return None
    if args.action == "pending-writes":
        _print_pending_writes(conn)
    elif args.action == "propose":
        update_id = propose_tune_update(conn, args.iteration_id, args.build_id, json.loads(args.settings_json), cli_text=args.cli_text)
        emit({"update_id": update_id}, args.json)
    elif args.action == "approve-for-write":
        approve_for_write(conn, args.update_id)
        emit({"update_id": args.update_id, "status": "approved_pending_write"}, args.json)
    elif args.action == "record-write-failure":
        record_application_failure(conn, args.update_id, args.failure)
        emit({"update_id": args.update_id, "status": "write_failed"}, args.json)
    elif args.action == "apply":
        mark_applied(conn, args.update_id)
        emit({"update_id": args.update_id, "status": "applied"}, args.json)
    elif args.action == "reject":
        reject(conn, args.update_id, args.reason)
        emit({"update_id": args.update_id, "status": "rejected"}, args.json)
    else:
        return None
    return 0


def _print_pending_writes(conn: Any) -> None:
    rows = conn.execute(
        """
        SELECT
          u.id AS update_id,
          u.iteration_id,
          u.build_id,
          u.settings_json,
          u.cli_text,
          u.application_failure,
          d.body AS diagnosis,
          d.confidence AS diagnosis_confidence
        FROM tune_updates u
        LEFT JOIN diagnoses d ON d.iteration_id = u.iteration_id
        WHERE u.status IN ('approved_pending_write', 'write_failed')
        ORDER BY u.decided_at, u.id
        """
    ).fetchall()
    payload = []
    for row in rows:
        item = row_to_dict(row)
        item["settings"] = json.loads(item.pop("settings_json"))
        payload.append(item)
    print_json(payload)
