from __future__ import annotations

import json
from typing import Any


def workbench_state(conn: Any, loop_id: int, agent_process_running: bool = False) -> dict[str, Any]:
    loop = _row_dict(
        conn.execute(
            """
            SELECT l.*, b.name AS build_name
            FROM loops l
            JOIN builds b ON b.id = l.build_id
            WHERE l.id = ?
            """,
            (loop_id,),
        ).fetchone()
    )
    if not loop:
        return {}
    agent_session = _row_dict(conn.execute("SELECT * FROM tuning_agent_sessions WHERE loop_id = ?", (loop_id,)).fetchone())
    tasks = _loop_tasks(conn, loop_id)
    notifications = _loop_notifications(conn, loop_id)
    iterations = _loop_iterations(conn, loop_id)
    events = _activity_events(agent_session, tasks, notifications, iterations)
    open_tasks = [task for task in tasks if task["status"] == "open"]
    open_notifications = [notification for notification in notifications if notification["status"] == "open"]
    return {
        "loop": loop,
        "agent_session": agent_session,
        "agent_process_running": agent_process_running,
        "loops": _loop_choices(conn),
        "builds": conn.execute("SELECT id, name FROM builds ORDER BY name, id").fetchall(),
        "tasks": tasks,
        "notifications": notifications,
        "iterations": iterations,
        "current_task": open_tasks[0] if open_tasks else None,
        "open_notifications": open_notifications,
        "open_task_count": len(open_tasks),
        "open_notification_count": len(open_notifications),
        "events": events,
    }


def _row_dict(row: Any) -> dict[str, Any] | None:
    return dict(row) if row else None


def _loop_choices(conn: Any) -> list[Any]:
    return conn.execute(
        """
        SELECT l.*, b.name AS build_name
        FROM loops l
        JOIN builds b ON b.id = l.build_id
        ORDER BY l.status = 'open' DESC, l.created_at DESC, l.id DESC
        """
    ).fetchall()


def _loop_tasks(conn: Any, loop_id: int) -> list[dict[str, Any]]:
    tasks = []
    for row in conn.execute("SELECT * FROM operator_tasks ORDER BY created_at, id").fetchall():
        task = _row_dict(row)
        task["payload"] = json.loads(task["payload_json"] or "{}")
        if _task_loop_id(conn, task) == loop_id:
            tasks.append(task)
    return tasks


def _loop_notifications(conn: Any, loop_id: int) -> list[dict[str, Any]]:
    notifications = []
    for row in conn.execute("SELECT * FROM operator_notifications ORDER BY created_at, id").fetchall():
        notification = _row_dict(row)
        notification["payload"] = json.loads(notification["payload_json"] or "{}")
        if notification["payload"].get("loop_id") == loop_id:
            notifications.append(notification)
    return notifications


def _loop_iterations(conn: Any, loop_id: int) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT
          i.*,
          d.body AS diagnosis_body,
          d.confidence AS diagnosis_confidence,
          u.id AS tune_update_id,
          u.status AS tune_update_status
        FROM tuning_iterations i
        LEFT JOIN diagnoses d ON d.iteration_id = i.id
        LEFT JOIN tune_updates u ON u.iteration_id = i.id
        WHERE i.loop_id = ?
        ORDER BY i.created_at, i.id
        """,
        (loop_id,),
    ).fetchall()
    return [_row_dict(row) for row in rows]


def _task_loop_id(conn: Any, task: dict[str, Any]) -> int | None:
    payload = task.get("payload") or {}
    loop_id = payload.get("loop_id")
    if loop_id is not None:
        return int(loop_id)
    update_id = payload.get("tune_update_id")
    if update_id is None:
        return None
    row = conn.execute(
        """
        SELECT i.loop_id
        FROM tune_updates u
        JOIN tuning_iterations i ON i.id = u.iteration_id
        WHERE u.id = ?
        """,
        (int(update_id),),
    ).fetchone()
    return int(row["loop_id"]) if row else None


def _activity_events(
    agent_session: dict[str, Any] | None,
    tasks: list[dict[str, Any]],
    notifications: list[dict[str, Any]],
    iterations: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    if agent_session:
        events.append(
            {
                "kind": "agent_status",
                "type_label": "Tuning Agent",
                "title": "Tuning Agent status",
                "body": f"Tuning Agent is {agent_session['status']}.",
                "created_at": agent_session["updated_at"],
                "status_label": agent_session["status"],
            }
        )
    events.extend(_task_events(tasks))
    events.extend(_notification_events(notifications))
    events.extend(_iteration_events(iterations))
    events.sort(key=lambda event: (event.get("created_at") or "", event.get("title") or ""))
    return events


def _iteration_events(iterations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    events = []
    for iteration in iterations:
        status = iteration.get("result") or iteration.get("status")
        if iteration.get("tune_update_id"):
            body = f"Tune Update #{iteration['tune_update_id']} is {iteration['tune_update_status']}."
        elif iteration.get("diagnosis_body"):
            body = str(iteration["diagnosis_body"])
        else:
            body = "Tuning Iteration started."
        no_change_reason = str(iteration.get("no_change_reason") or "").strip()
        if no_change_reason:
            body = f"{body} Reason: {no_change_reason}"
        events.append(
            {
                "kind": "tuning_iteration",
                "type_label": "Tuning Iteration",
                "title": f"#{iteration['id']} {(_humanize_token(status) or 'open')}",
                "body": body,
                "created_at": iteration.get("completed_at") or iteration.get("created_at"),
                "status": status,
                "status_label": _humanize_token(status),
            }
        )
    return events


def _task_events(tasks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "kind": "operator_task",
            "type_label": "Operator Task",
            "title": f"#{task['id']} {task['title']}",
            "body": _operator_task_activity_body(task),
            "created_at": task["resolved_at"] or task["created_at"],
            "status": task["status"],
            "status_label": _humanize_token(task["status"]),
            "task_id": task["id"],
            "href": f"/tasks/{task['id']}",
        }
        for task in tasks
    ]


def _notification_events(notifications: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "kind": "operator_notification",
            "type_label": "Operator Notification",
            "title": f"#{notification['id']} {notification['title']}",
            "body": notification["body"],
            "created_at": notification["acknowledged_at"] or notification["created_at"],
            "status": notification["status"],
            "status_label": _humanize_token(notification["status"]),
            "notification_id": notification["id"],
            "href": f"/notifications/{notification['id']}",
        }
        for notification in notifications
    ]


def _operator_task_activity_body(task: dict[str, Any]) -> str:
    if task["status"] != "resolved" or not task.get("response_json"):
        return task["body"]
    try:
        response = json.loads(task["response_json"])
    except json.JSONDecodeError:
        return "Operator responded."
    if not isinstance(response, dict):
        return "Operator responded."
    decision = _humanize_token(response.get("decision")) or "responded"
    notes = str(response.get("notes") or "").strip()
    text = f"Operator {decision} task."
    if notes:
        text += f" Notes: {notes}"
    else:
        text += " Notes: none."
    return text


def _humanize_token(value: object) -> str:
    return str(value or "").replace("_", " ").strip()
