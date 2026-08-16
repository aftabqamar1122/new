"""Gmail and Calendar tool definitions, shared by both agents.

Schemas live next to their dispatch so either agent can pick them up without
depending on the other's model SDK. Importing this module requires the Google
client libraries; callers should check availability first.
"""

from typing import Any

from tools.calendar_tools import get_calendar_events, create_calendar_event, delete_calendar_event
from tools.email_tools import get_emails, send_email, reply_to_email
from tools.task_tools import list_tasks

SCHEMAS: list[dict] = [
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
]

NAMES = frozenset(schema["name"] for schema in SCHEMAS)


def morning_brief() -> dict[str, Any]:
    """Composite tool: emails + calendar + tasks in one call."""
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


HANDLERS = {
    "get_emails": lambda i: get_emails(**i),
    "send_email": lambda i: send_email(**i),
    "reply_to_email": lambda i: reply_to_email(**i),
    "get_calendar_events": lambda i: get_calendar_events(**i),
    "create_calendar_event": lambda i: create_calendar_event(**i),
    "delete_calendar_event": lambda i: delete_calendar_event(**i),
    "get_morning_brief": lambda _: morning_brief(),
}


def execute(name: str, inputs: dict) -> Any:
    handler = HANDLERS.get(name)
    if handler is None:
        return {"error": f"Unknown tool: {name}"}
    return handler(inputs)
