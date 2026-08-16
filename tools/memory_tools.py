"""Long-term memory for the personal agent — facts about the user and past chats.

Everything lives in a local SQLite file (~/.personal_agent/memory.db). Nothing
leaves the machine except what the agent sends to the Anthropic API as context.
"""

import sqlite3
from pathlib import Path
from typing import Any

DB_PATH = Path.home() / ".personal_agent" / "memory.db"

CATEGORIES = ("profile", "preference", "person", "project", "event", "general")


def _conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(DB_PATH))
    con.row_factory = sqlite3.Row
    con.execute("""
        CREATE TABLE IF NOT EXISTS memories (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            category   TEXT DEFAULT 'general',
            content    TEXT NOT NULL,
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now'))
        )
    """)
    con.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            role       TEXT NOT NULL,
            content    TEXT NOT NULL,
            created_at TEXT DEFAULT (datetime('now'))
        )
    """)
    con.commit()
    return con


# --- facts the agent knows about you ---------------------------------------


def remember(content: str, category: str = "general") -> dict[str, Any]:
    """Store a fact about the user. Skips near-duplicates of what's already known."""
    try:
        if category not in CATEGORIES:
            category = "general"
        with _conn() as con:
            existing = con.execute(
                "SELECT id FROM memories WHERE lower(content) = lower(?)", (content.strip(),)
            ).fetchone()
            if existing:
                return {"success": True, "memory_id": existing["id"], "message": "Already remembered."}

            cur = con.execute(
                "INSERT INTO memories (category, content) VALUES (?, ?)",
                (category, content.strip()),
            )
            return {"success": True, "memory_id": cur.lastrowid, "message": f"Remembered: {content}"}
    except Exception as e:
        return {"error": str(e)}


def recall(query: str = "", category: str = "", limit: int = 25) -> dict[str, Any]:
    """Search stored memories. An empty query returns the most recent ones."""
    try:
        sql = "SELECT * FROM memories"
        params: list[Any] = []
        clauses = []

        words = [w for w in query.split() if len(w) > 2]
        if words:
            clauses.append("(" + " OR ".join("content LIKE ?" for _ in words) + ")")
            params.extend(f"%{w}%" for w in words)
        if category:
            clauses.append("category = ?")
            params.append(category)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)

        sql += " ORDER BY updated_at DESC LIMIT ?"
        params.append(max(1, min(limit, 100)))

        with _conn() as con:
            rows = [dict(r) for r in con.execute(sql, params).fetchall()]
        return {"memories": rows, "total": len(rows)}
    except Exception as e:
        return {"error": str(e)}


def update_memory(memory_id: int, content: str) -> dict[str, Any]:
    """Correct a fact that has changed."""
    try:
        with _conn() as con:
            cur = con.execute(
                "UPDATE memories SET content = ?, updated_at = datetime('now') WHERE id = ?",
                (content.strip(), memory_id),
            )
            if cur.rowcount == 0:
                return {"error": f"No memory with id {memory_id}."}
        return {"success": True, "message": f"Memory #{memory_id} updated."}
    except Exception as e:
        return {"error": str(e)}


def forget(memory_id: int) -> dict[str, Any]:
    """Delete a stored fact."""
    try:
        with _conn() as con:
            cur = con.execute("DELETE FROM memories WHERE id = ?", (memory_id,))
            if cur.rowcount == 0:
                return {"error": f"No memory with id {memory_id}."}
        return {"success": True, "message": f"Forgot memory #{memory_id}."}
    except Exception as e:
        return {"error": str(e)}


def profile_summary(limit: int = 60) -> str:
    """Render known facts as bullet lines for the system prompt."""
    try:
        with _conn() as con:
            rows = con.execute(
                "SELECT category, content FROM memories ORDER BY category, updated_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
    except Exception:
        return ""

    if not rows:
        return ""
    return "\n".join(f"- ({r['category']}) {r['content']}" for r in rows)


# --- conversation continuity across sessions --------------------------------


def log_message(role: str, content: str) -> None:
    """Persist one plain-text turn so the next session can pick up the thread."""
    if not content.strip():
        return
    try:
        with _conn() as con:
            con.execute("INSERT INTO messages (role, content) VALUES (?, ?)", (role, content.strip()))
    except Exception:
        pass  # memory logging must never break the conversation


def recent_messages(limit: int = 20) -> list[dict[str, str]]:
    """Return the last `limit` turns, oldest first, ready to seed agent history."""
    try:
        with _conn() as con:
            rows = con.execute(
                "SELECT role, content FROM messages ORDER BY id DESC LIMIT ?", (max(0, limit),)
            ).fetchall()
    except Exception:
        return []
    return [{"role": r["role"], "content": r["content"]} for r in reversed(rows)]


def clear_history() -> dict[str, Any]:
    """Wipe the stored conversation log. Stored facts are kept."""
    try:
        with _conn() as con:
            con.execute("DELETE FROM messages")
        return {"success": True, "message": "Conversation history cleared."}
    except Exception as e:
        return {"error": str(e)}


def stats() -> dict[str, int]:
    try:
        with _conn() as con:
            facts = con.execute("SELECT COUNT(*) c FROM memories").fetchone()["c"]
            turns = con.execute("SELECT COUNT(*) c FROM messages").fetchone()["c"]
        return {"facts": facts, "turns": turns}
    except Exception:
        return {"facts": 0, "turns": 0}
