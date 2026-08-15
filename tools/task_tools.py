"""Local task and reminder management using SQLite."""

import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

DB_PATH = Path.home() / ".daily_agent" / "tasks.db"


def _conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(DB_PATH))
    con.row_factory = sqlite3.Row
    con.execute("""
        CREATE TABLE IF NOT EXISTS tasks (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            title     TEXT NOT NULL,
            description TEXT DEFAULT '',
            due_date  TEXT,
            priority  TEXT DEFAULT 'medium',
            status    TEXT DEFAULT 'pending',
            created_at TEXT DEFAULT (datetime('now'))
        )
    """)
    con.commit()
    return con


def add_task(
    title: str,
    description: str = "",
    due_date: str = "",
    priority: str = "medium",
) -> dict[str, Any]:
    """Add a new task or reminder."""
    try:
        with _conn() as con:
            cur = con.execute(
                "INSERT INTO tasks (title, description, due_date, priority) VALUES (?, ?, ?, ?)",
                (title, description, due_date or None, priority),
            )
            task_id = cur.lastrowid
        return {"success": True, "task_id": task_id, "message": f"Task #{task_id} '{title}' added."}
    except Exception as e:
        return {"error": str(e)}


def list_tasks(status: str = "pending", priority: str = "") -> dict[str, Any]:
    """List tasks filtered by status and/or priority."""
    try:
        with _conn() as con:
            query = "SELECT * FROM tasks"
            params: list[Any] = []

            conditions = []
            if status and status != "all":
                conditions.append("status = ?")
                params.append(status)
            if priority:
                conditions.append("priority = ?")
                params.append(priority)
            if conditions:
                query += " WHERE " + " AND ".join(conditions)
            query += " ORDER BY CASE priority WHEN 'high' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END, due_date ASC"

            rows = con.execute(query, params).fetchall()
            tasks = [dict(r) for r in rows]

        return {"tasks": tasks, "total": len(tasks)}
    except Exception as e:
        return {"error": str(e)}


def complete_task(task_id: int) -> dict[str, Any]:
    """Mark a task as completed."""
    try:
        with _conn() as con:
            con.execute(
                "UPDATE tasks SET status = 'completed' WHERE id = ?", (task_id,)
            )
            if con.execute("SELECT changes()").fetchone()[0] == 0:
                return {"error": f"Task #{task_id} not found."}
        return {"success": True, "message": f"Task #{task_id} marked as completed."}
    except Exception as e:
        return {"error": str(e)}


def delete_task(task_id: int) -> dict[str, Any]:
    """Delete a task permanently."""
    try:
        with _conn() as con:
            con.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
            if con.execute("SELECT changes()").fetchone()[0] == 0:
                return {"error": f"Task #{task_id} not found."}
        return {"success": True, "message": f"Task #{task_id} deleted."}
    except Exception as e:
        return {"error": str(e)}


def update_task(
    task_id: int,
    title: str = "",
    description: str = "",
    due_date: str = "",
    priority: str = "",
) -> dict[str, Any]:
    """Update an existing task's fields."""
    try:
        with _conn() as con:
            fields, params = [], []
            if title:
                fields.append("title = ?"); params.append(title)
            if description:
                fields.append("description = ?"); params.append(description)
            if due_date:
                fields.append("due_date = ?"); params.append(due_date)
            if priority:
                fields.append("priority = ?"); params.append(priority)
            if not fields:
                return {"error": "No fields provided to update."}
            params.append(task_id)
            con.execute(f"UPDATE tasks SET {', '.join(fields)} WHERE id = ?", params)
        return {"success": True, "message": f"Task #{task_id} updated."}
    except Exception as e:
        return {"error": str(e)}
