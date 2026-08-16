"""Core AI agent — Anthropic tool-use loop over daily-activity tools."""

import json
from datetime import datetime
from typing import Any

import anthropic

from tools import google_tools
from tools.task_tools import add_task, list_tasks, complete_task, delete_task, update_task

MODEL = "claude-sonnet-5"

TASK_TOOLS: list[dict] = [
    {
        "name": "add_task",
        "description": "Add a new task or reminder.",
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Task title"},
                "description": {"type": "string", "description": "Optional details"},
                "due_date": {"type": "string", "description": "Due date as YYYY-MM-DD"},
                "priority": {
                    "type": "string",
                    "enum": ["low", "medium", "high"],
                    "description": "Task priority (default: medium)",
                },
            },
            "required": ["title"],
        },
    },
    {
        "name": "list_tasks",
        "description": "List tasks and reminders, optionally filtered.",
        "input_schema": {
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "enum": ["pending", "completed", "all"],
                    "description": "Filter by status (default: pending)",
                },
                "priority": {
                    "type": "string",
                    "enum": ["low", "medium", "high"],
                    "description": "Filter by priority",
                },
            },
        },
    },
    {
        "name": "complete_task",
        "description": "Mark a task as completed.",
        "input_schema": {
            "type": "object",
            "properties": {
                "task_id": {"type": "integer", "description": "Task ID (from list_tasks)"},
            },
            "required": ["task_id"],
        },
    },
    {
        "name": "delete_task",
        "description": "Permanently delete a task.",
        "input_schema": {
            "type": "object",
            "properties": {
                "task_id": {"type": "integer", "description": "Task ID (from list_tasks)"},
            },
            "required": ["task_id"],
        },
    },
    {
        "name": "update_task",
        "description": "Update the title, description, due date, or priority of an existing task.",
        "input_schema": {
            "type": "object",
            "properties": {
                "task_id": {"type": "integer", "description": "Task ID to update"},
                "title": {"type": "string", "description": "New title"},
                "description": {"type": "string", "description": "New description"},
                "due_date": {"type": "string", "description": "New due date as YYYY-MM-DD"},
                "priority": {"type": "string", "enum": ["low", "medium", "high"], "description": "New priority"},
            },
            "required": ["task_id"],
        },
    },
]

TOOLS: list[dict] = google_tools.SCHEMAS + TASK_TOOLS

SYSTEM_PROMPT = f"""You are a personal AI assistant managing daily activities for your user.
Today's date is {{date}}.

Your capabilities:
- Email: read inbox, search emails, send new emails, reply to threads
- Calendar: view upcoming events, create/delete events with Google Meet links
- Tasks: add, list, complete, update, and delete tasks and reminders
- Morning brief: a combined summary of emails, calendar, and tasks

Guidelines:
- Be concise and action-oriented. After completing a tool call, summarize the result clearly.
- When the user asks to "send" or "reply", always confirm recipient and content before sending unless they gave complete details.
- For calendar events, ask for the time/date if not provided.
- For tasks, default priority is "medium" unless otherwise specified.
- Format dates as readable strings (e.g. "Monday, August 15 at 10:00 AM") when presenting to the user.
- If a tool returns an error, explain it clearly and suggest next steps.
"""


def _execute_tool(name: str, inputs: dict) -> Any:
    """Route a tool call to the matching Python function."""
    if name in google_tools.NAMES:
        return google_tools.execute(name, inputs)

    handlers = {
        "add_task": lambda i: add_task(**i),
        "list_tasks": lambda i: list_tasks(**i),
        "complete_task": lambda i: complete_task(**i),
        "delete_task": lambda i: delete_task(**i),
        "update_task": lambda i: update_task(**i),
    }
    handler = handlers.get(name)
    if handler is None:
        return {"error": f"Unknown tool: {name}"}
    return handler(inputs)


class DailyAgent:
    def __init__(self, api_key: str):
        self.client = anthropic.Anthropic(api_key=api_key)
        self.history: list[dict] = []

    def chat(self, user_message: str) -> str:
        """Send a user message and return the agent's response."""
        self.history.append({"role": "user", "content": user_message})

        system = SYSTEM_PROMPT.format(date=datetime.now().strftime("%A, %B %d, %Y"))

        while True:
            response = self.client.messages.create(
                model=MODEL,
                max_tokens=4096,
                system=system,
                tools=TOOLS,
                messages=self.history,
            )

            # Collect all tool calls and text from this response
            tool_results = []
            text_blocks = []

            for block in response.content:
                if block.type == "tool_use":
                    result = _execute_tool(block.name, block.input)
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": json.dumps(result, default=str),
                    })
                elif block.type == "text":
                    text_blocks.append(block.text)

            # If the model made tool calls, feed results back
            if tool_results:
                self.history.append({"role": "assistant", "content": response.content})
                self.history.append({"role": "user", "content": tool_results})
                continue

            # No tool calls → final text response
            final_text = "\n".join(text_blocks).strip()
            self.history.append({"role": "assistant", "content": final_text})
            return final_text

    def reset(self):
        """Clear conversation history."""
        self.history = []
