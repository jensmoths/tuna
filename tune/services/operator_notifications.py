from __future__ import annotations

import json
import sqlite3
from typing import Any


def create_notification(conn: sqlite3.Connection, kind: str, title: str, *, body: str = "", payload: dict[str, Any] | None = None) -> int:
    cur = conn.execute(
        "INSERT INTO operator_notifications (kind, title, body, payload_json) VALUES (?, ?, ?, ?)",
        (kind, title, body, json.dumps(payload or {}, sort_keys=True)),
    )
    conn.commit()
    return int(cur.lastrowid)


def create_blackbox_config_notification(
    conn: sqlite3.Connection,
    *,
    settings: dict[str, Any],
    reason: str,
    build_id: int | None = None,
    loop_id: int | None = None,
    previous_settings: dict[str, Any] | None = None,
    impact: str = "",
) -> int:
    body = (
        "The Tuning Agent changed diagnostic Blackbox/logging settings through FCS. "
        "This Operator Notification records the change for Operator awareness; it is not a Tune Update."
    )
    payload = {
        "build_id": build_id,
        "loop_id": loop_id,
        "settings": settings,
        "previous_settings": previous_settings or {},
        "reason": reason,
        "impact": impact,
        "requires_operator_approval": False,
        "write_path": "FCS",
    }
    return create_notification(
        conn,
        "blackbox_config_changed",
        "Blackbox/logging settings changed",
        body=body,
        payload=payload,
    )


def acknowledge_notification(conn: sqlite3.Connection, notification_id: int, response: dict[str, Any]) -> None:
    conn.execute(
        """
        UPDATE operator_notifications
        SET status = 'acknowledged', acknowledged_json = ?, acknowledged_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (json.dumps(response, sort_keys=True), notification_id),
    )
    conn.commit()
