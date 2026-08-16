"""Personal agent — a conversational assistant that remembers you.

Core capabilities (always available, no external accounts needed):
  - natural conversation with memory that survives restarts
  - long-term facts about you: name, work, preferences, people, projects
  - tasks and reminders (local SQLite)

Optional: if Google credentials are set up (see README), email and calendar
tools are attached automatically at startup.
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

import anthropic

from tools import memory_tools
from tools.task_tools import add_task, list_tasks, complete_task, delete_task, update_task

MODEL = "claude-sonnet-5"
MAX_TOKENS = 4096

# Turns of previous conversation reloaded at startup.
HISTORY_WINDOW = 20

GOOGLE_TOOL_NAMES = {
    "get_emails",
    "send_email",
    "reply_to_email",
    "get_calendar_events",
    "create_calendar_event",
    "delete_calendar_event",
    "get_morning_brief",
}

CORE_TOOLS: list[dict] = [
    {
        "name": "remember",
        "description": (
            "Store a durable fact about the user so it is available in future conversations. "
            "Use this whenever the user shares something worth keeping: their name, job, where "
            "they live, preferences, goals, important people, ongoing projects. Do not use it "
            "for passing small talk."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "content": {
                    "type": "string",
                    "description": "The fact, written as a short standalone sentence, e.g. 'Prefers morning meetings.'",
                },
                "category": {
                    "type": "string",
                    "enum": list(memory_tools.CATEGORIES),
                    "description": "profile (identity/work), preference, person, project, event, or general",
                },
            },
            "required": ["content"],
        },
    },
    {
        "name": "recall",
        "description": (
            "Search stored facts about the user. Use when you need details that are not in the "
            "current conversation, or when the user asks what you know about them."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Keywords to search for. Omit to list recent memories."},
                "category": {
                    "type": "string",
                    "enum": list(memory_tools.CATEGORIES),
                    "description": "Restrict results to one category",
                },
                "limit": {"type": "integer", "description": "Max results (default 25)"},
            },
        },
    },
    {
        "name": "update_memory",
        "description": "Correct a stored fact that has changed. Get the id from recall first.",
        "input_schema": {
            "type": "object",
            "properties": {
                "memory_id": {"type": "integer", "description": "Memory id from recall"},
                "content": {"type": "string", "description": "The corrected fact"},
            },
            "required": ["memory_id", "content"],
        },
    },
    {
        "name": "forget",
        "description": "Delete a stored fact, e.g. when the user asks you to forget something.",
        "input_schema": {
            "type": "object",
            "properties": {
                "memory_id": {"type": "integer", "description": "Memory id from recall"},
            },
            "required": ["memory_id"],
        },
    },
    {
        "name": "add_task",
        "description": "Add a task or reminder for the user.",
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Task title"},
                "description": {"type": "string", "description": "Optional details"},
                "due_date": {"type": "string", "description": "Due date as YYYY-MM-DD"},
                "priority": {"type": "string", "enum": ["low", "medium", "high"], "description": "Default medium"},
            },
            "required": ["title"],
        },
    },
    {
        "name": "list_tasks",
        "description": "List the user's tasks and reminders.",
        "input_schema": {
            "type": "object",
            "properties": {
                "status": {"type": "string", "enum": ["pending", "completed", "all"], "description": "Default pending"},
                "priority": {"type": "string", "enum": ["low", "medium", "high"], "description": "Filter by priority"},
            },
        },
    },
    {
        "name": "complete_task",
        "description": "Mark a task as done.",
        "input_schema": {
            "type": "object",
            "properties": {"task_id": {"type": "integer", "description": "Task id from list_tasks"}},
            "required": ["task_id"],
        },
    },
    {
        "name": "update_task",
        "description": "Change a task's title, details, due date, or priority.",
        "input_schema": {
            "type": "object",
            "properties": {
                "task_id": {"type": "integer", "description": "Task id from list_tasks"},
                "title": {"type": "string", "description": "New title"},
                "description": {"type": "string", "description": "New details"},
                "due_date": {"type": "string", "description": "New due date as YYYY-MM-DD"},
                "priority": {"type": "string", "enum": ["low", "medium", "high"], "description": "New priority"},
            },
            "required": ["task_id"],
        },
    },
    {
        "name": "delete_task",
        "description": "Permanently delete a task.",
        "input_schema": {
            "type": "object",
            "properties": {"task_id": {"type": "integer", "description": "Task id from list_tasks"}},
            "required": ["task_id"],
        },
    },
]

CORE_HANDLERS: dict[str, Callable[[dict], Any]] = {
    "remember": lambda i: memory_tools.remember(**i),
    "recall": lambda i: memory_tools.recall(**i),
    "update_memory": lambda i: memory_tools.update_memory(**i),
    "forget": lambda i: memory_tools.forget(**i),
    "add_task": lambda i: add_task(**i),
    "list_tasks": lambda i: list_tasks(**i),
    "complete_task": lambda i: complete_task(**i),
    "update_task": lambda i: update_task(**i),
    "delete_task": lambda i: delete_task(**i),
}

SYSTEM_PROMPT = """You are {agent_name}, {user}'s personal AI companion. \
You talk with them day to day: catching up, thinking things through, keeping track of what \
matters to them, and handling small errands like tasks and reminders.

Today is {date}.

How to be:
- Talk like a thoughtful friend, not a help desk. Warm, direct, and brief by default — a \
sentence or two for small talk, more only when the subject earns it.
- Be genuinely engaged: ask a follow-up when you're curious, and remember what they told you \
last time instead of asking again.
- Have a point of view. If they ask what you think, answer honestly rather than listing options.
- Don't open every reply with praise for their question, and don't announce what you're about \
to do — just do it.

Memory:
- When they share something durable about themselves — their name, work, where they live, \
preferences, people they care about, projects, plans — call `remember` so it survives to the \
next conversation. Do it quietly; don't narrate it every time.
- If something you know turns out to be outdated, call `update_memory`. If they ask you to \
forget something, call `forget`.
- Use `recall` before claiming you don't know something about them.

Everything else:
- Tasks and reminders: use the task tools. Never invent a task id — list first.
- Before sending anything on their behalf (email, calendar invites), confirm the details.
- If a tool errors, say what failed in plain language and suggest the next step.
{profile_block}"""

PROFILE_HEADER = """
What you already know about {user}:
{facts}
"""


def _google_ready() -> bool:
    """True when the Google client libs are installed and credentials exist."""
    try:
        import googleapiclient  # noqa: F401
    except ImportError:
        return False
    token = Path.home() / ".daily_agent" / "token.json"
    return token.exists() or Path("credentials.json").exists()


def _load_google_tools() -> tuple[list[dict], dict[str, Callable[[dict], Any]]]:
    """Attach the Gmail/Calendar tools from agent.py, if they're usable."""
    if not _google_ready():
        return [], {}
    try:
        from agent import TOOLS as daily_tools, _execute_tool as run_daily
    except Exception:
        return [], {}

    schemas = [t for t in daily_tools if t["name"] in GOOGLE_TOOL_NAMES]
    handlers = {
        t["name"]: (lambda name: lambda i: run_daily(name, i))(t["name"])
        for t in schemas
    }
    return schemas, handlers


def _alternating(messages: list[dict]) -> list[dict]:
    """Make a reloaded transcript API-safe: start on a user turn, no repeats.

    A session that crashed mid-reply can leave a user turn with no answer, so
    the stored log isn't guaranteed to alternate.
    """
    cleaned: list[dict] = []
    for msg in messages:
        if not cleaned and msg["role"] != "user":
            continue
        if cleaned and cleaned[-1]["role"] == msg["role"]:
            cleaned[-1] = msg if msg["role"] == "user" else cleaned[-1]
            continue
        cleaned.append(msg)
    return cleaned


class PersonalAgent:
    """Conversational agent with persistent memory over the local tool set."""

    def __init__(self, api_key: str, agent_name: str = "Ava", user_name: str = "", resume: bool = True):
        self.client = anthropic.Anthropic(api_key=api_key)
        self.agent_name = agent_name
        self.user_name = user_name

        google_tools, google_handlers = _load_google_tools()
        self.tools = CORE_TOOLS + google_tools
        self.handlers = {**CORE_HANDLERS, **google_handlers}
        self.google_enabled = bool(google_tools)

        self.history: list[dict] = _alternating(memory_tools.recent_messages(HISTORY_WINDOW)) if resume else []
        self.resumed_turns = len(self.history)

    # --- prompt -------------------------------------------------------------

    def _system_prompt(self) -> str:
        facts = memory_tools.profile_summary()
        user = self.user_name or "your user"
        profile_block = PROFILE_HEADER.format(user=user, facts=facts) if facts else ""
        return SYSTEM_PROMPT.format(
            agent_name=self.agent_name,
            user=user,
            date=datetime.now().strftime("%A, %B %d, %Y"),
            profile_block=profile_block,
        )

    # --- tool dispatch ------------------------------------------------------

    def _run_tool(self, name: str, inputs: dict) -> Any:
        handler = self.handlers.get(name)
        if handler is None:
            return {"error": f"Unknown tool: {name}"}
        try:
            return handler(inputs)
        except TypeError as e:
            return {"error": f"Bad arguments for {name}: {e}"}
        except Exception as e:
            return {"error": f"{name} failed: {e}"}

    # --- conversation -------------------------------------------------------

    def chat(self, user_message: str, on_text: Callable[[str], None] | None = None) -> str:
        """Send a message and return the reply.

        If `on_text` is given it receives text deltas as they stream in.
        """
        self.history.append({"role": "user", "content": user_message})
        memory_tools.log_message("user", user_message)

        reply_parts: list[str] = []

        while True:
            # Rebuilt each round-trip so a fact stored by `remember` mid-turn is
            # already part of the profile the model sees on the next round-trip.
            with self.client.messages.stream(
                model=MODEL,
                max_tokens=MAX_TOKENS,
                system=self._system_prompt(),
                tools=self.tools,
                messages=self.history,
            ) as stream:
                for delta in stream.text_stream:
                    if on_text:
                        on_text(delta)
                response = stream.get_final_message()

            tool_results = []
            for block in response.content:
                if block.type == "text":
                    reply_parts.append(block.text)
                elif block.type == "tool_use":
                    result = self._run_tool(block.name, block.input)
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": json.dumps(result, default=str),
                    })

            self.history.append({"role": "assistant", "content": response.content})

            if tool_results:
                self.history.append({"role": "user", "content": tool_results})
                continue

            reply = "\n".join(p for p in reply_parts if p.strip()).strip()
            memory_tools.log_message("assistant", reply)
            return reply

    def reset(self, forget_history: bool = False) -> None:
        """Start a fresh conversation. Stored facts about the user are kept.

        With `forget_history`, the persisted transcript is deleted too.
        """
        self.history = []
        self.resumed_turns = 0
        if forget_history:
            memory_tools.clear_history()
