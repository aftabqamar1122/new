"""Google Calendar tools — read and create events."""

from datetime import datetime, timedelta, timezone
from typing import Any

from googleapiclient.discovery import build

from auth.google_auth import get_credentials


def _calendar():
    return build("calendar", "v3", credentials=get_credentials())


def _format_event(event: dict) -> dict:
    start = event.get("start", {})
    end = event.get("end", {})
    return {
        "id": event.get("id"),
        "title": event.get("summary", "(No title)"),
        "start": start.get("dateTime") or start.get("date"),
        "end": end.get("dateTime") or end.get("date"),
        "location": event.get("location", ""),
        "description": (event.get("description") or "")[:300],
        "attendees": [a.get("email") for a in event.get("attendees", [])],
        "meet_link": event.get("hangoutLink", ""),
        "status": event.get("status", "confirmed"),
    }


def get_calendar_events(
    date: str = "", days_ahead: int = 1, max_results: int = 20
) -> dict[str, Any]:
    """Fetch calendar events for a given date range."""
    try:
        svc = _calendar()

        if date:
            start_dt = datetime.fromisoformat(date).replace(tzinfo=timezone.utc)
        else:
            start_dt = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)

        end_dt = start_dt + timedelta(days=max(days_ahead, 1))

        result = svc.events().list(
            calendarId="primary",
            timeMin=start_dt.isoformat(),
            timeMax=end_dt.isoformat(),
            maxResults=max_results,
            singleEvents=True,
            orderBy="startTime",
        ).execute()

        events = [_format_event(e) for e in result.get("items", [])]
        label = date or "today"
        return {
            "events": events,
            "total": len(events),
            "date_range": f"{start_dt.date()} to {end_dt.date()}",
            "message": f"Found {len(events)} event(s) for {label}." if events else f"No events found for {label}.",
        }
    except Exception as e:
        return {"error": str(e)}


def create_calendar_event(
    title: str,
    start_time: str,
    end_time: str,
    description: str = "",
    attendees: list[str] | None = None,
) -> dict[str, Any]:
    """Create a new Google Calendar event."""
    try:
        svc = _calendar()

        body: dict[str, Any] = {
            "summary": title,
            "start": {"dateTime": start_time, "timeZone": "UTC"},
            "end": {"dateTime": end_time, "timeZone": "UTC"},
        }
        if description:
            body["description"] = description
        if attendees:
            body["attendees"] = [{"email": e} for e in attendees]
            body["conferenceData"] = {
                "createRequest": {"requestId": f"meet-{title.replace(' ', '-')[:20]}"}
            }

        event = svc.events().insert(
            calendarId="primary",
            body=body,
            conferenceDataVersion=1 if attendees else 0,
        ).execute()

        return {
            "success": True,
            "event_id": event["id"],
            "title": event.get("summary"),
            "start": event["start"].get("dateTime"),
            "end": event["end"].get("dateTime"),
            "link": event.get("htmlLink"),
            "meet_link": event.get("hangoutLink", ""),
            "message": f"Event '{title}' created successfully.",
        }
    except Exception as e:
        return {"error": str(e)}


def delete_calendar_event(event_id: str) -> dict[str, Any]:
    """Delete a calendar event by ID."""
    try:
        svc = _calendar()
        svc.events().delete(calendarId="primary", eventId=event_id).execute()
        return {"success": True, "message": f"Event {event_id} deleted."}
    except Exception as e:
        return {"error": str(e)}
