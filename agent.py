"""Core AI agent — Anthropic tool-use loop over daily-activity tools."""

import json
from datetime import datetime
from typing import Any

import anthropic

from tools.email_tools import get_emails, send_email, reply_to_email
from tools.calendar_tools import get_calendar_events, create_calendar_event, delete_calendar_event
from tools.task_tools import add_task, list_tasks, complete_task, delete_task, update_task

MODEL = "claude-sonnet-5"

TOOLS: list[dict] = [
    {
        "name": "get_emails",
        "description": (
            "Fetch emails from the Gmail inbox. Use to read recent emails, "
            "check unread messages, or search for specific emails."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "max_results": {"type": "integer", "description": "Number of emails to fetch (default 10, max 50)"},
                "unread_only": {"type": "boolean", "description": "If true, only fetch unread emails"},
                "query": {"type": "string", "description": "Gmail search query, e.g. 'from:boss@co.com' or 'subject:invoice'"},
            },
        },
    },
    {
        "name": "send_email",
        "description": "Send a new email via Gmail.",
        "input_schema": {
            "type": "object",
            "properties": {
                "to": {"type": "string", "description": "Recipient email address"},
                "subject": {"type": "string", "description": "Email subject line"},
                "body": {"type": "string", "description": "Email body (plain text)"},
                "cc": {"type": "string", "description": "CC addresses, comma-separated"},
            },
            "required": ["to", "subject", "body"],
        },
    },
    {
        "name": "reply_to_email",
        "description": "Reply to an existing email thread. Use the message ID from get_emails.",
        "input_schema": {
            "type": "object",
            "properties": {
                "message_id": {"type": "string", "description": "Gmail message ID to reply to"},
                "body": {"type": "string", "description": "Reply body text"},
            },
            "required": ["message_id", "body"],
        },
    },
    {
        "name": "get_calendar_events",
        "description": "Fetch events from Google Calendar for a date or date range.",
        "input_schema": {
            "type": "object",
            "properties": {
                "date": {"type": "string", "description": "Start date in YYYY-MM-DD format (defaults to today)"},
                "days_ahead": {"type": "integer", "description": "How many days to look ahead (default 1)"},
                "max_results": {"type": "integer", "description": "Max events to return (default 20)"},
            },
        },
    },
    {
        "name": "create_calendar_event",
        "description": "Create a new event in Google Calendar.",
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Event title"},
                "start_time": {"type": "string", "description": "Start time in ISO 8601 format, e.g. '2024-01-15T10:00:00'"},
                "end_time": {"type": "string", "description": "End time in ISO 8601 format"},
                "description": {"type": "string", "description": "Event description"},
                "attendees": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of attendee email addresses",
                },
            },
            "required": ["title", "start_time", "end_time"],
        },
    },
    {
        "name": "delete_calendar_event",
        "description": "Delete a Google Calendar event by its ID.",
        "input_schema": {
            "type": "object",
            "properties": {
                "event_id": {"type": "string", "description": "Calendar event ID from get_calendar_events"},
            },
            "required": ["event_id"],
        },
    },
    {
        "name": "get_morning_brief",
        "description": (
            "Generate a morning brief — today's unread emails (up to 5), "
            "calendar events, and pending tasks. Call this at the start of the day."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
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
    handlers = {
        "get_emails": lambda i: get_emails(**i),
        "send_email": lambda i: send_email(**i),
        "reply_to_email": lambda i: reply_to_email(**i),
        "get_calendar_events": lambda i: get_calendar_events(**i),
        "create_calendar_event": lambda i: create_calendar_event(**i),
        "delete_calendar_event": lambda i: delete_calendar_event(**i),
        "get_morning_brief": lambda _: _morning_brief(),
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


def _morning_brief() -> dict:
    """Composite tool: emails + calendar + tasks."""
    emails = get_emails(max_results=5, unread_only=True)
    events = get_calendar_events()
    tasks = list_tasks(status="pending")
    return {
        "unread_emails": emails.get("emails", []),
        "email_count": emails.get("total", 0),
        "todays_events": events.get("events", []),
        "event_count": events.get("total", 0),
        "pending_tasks": tasks.get("tasks", []),
        "task_count": tasks.get("total", 0),
    }


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
