"""Gmail tools — read, search, and send emails."""

import base64
import email as email_lib
import re
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any

from googleapiclient.discovery import build

from auth.google_auth import get_credentials


def _gmail():
    return build("gmail", "v1", credentials=get_credentials())


def _decode_body(payload: dict) -> str:
    """Extract plain-text body from a Gmail message payload."""
    body = ""
    if "parts" in payload:
        for part in payload["parts"]:
            if part.get("mimeType") == "text/plain":
                data = part.get("body", {}).get("data", "")
                if data:
                    body = base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
                    break
        if not body:
            # Fall back to first part with data
            for part in payload["parts"]:
                data = part.get("body", {}).get("data", "")
                if data:
                    body = base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
                    break
    else:
        data = payload.get("body", {}).get("data", "")
        if data:
            body = base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")

    # Clean up excessive whitespace
    body = re.sub(r"\n{3,}", "\n\n", body).strip()
    return body[:2000] if len(body) > 2000 else body


def _header(headers: list[dict], name: str) -> str:
    for h in headers:
        if h["name"].lower() == name.lower():
            return h["value"]
    return ""


def get_emails(max_results: int = 10, unread_only: bool = False, query: str = "") -> dict[str, Any]:
    """Fetch emails from Gmail inbox."""
    try:
        svc = _gmail()
        q = query or ""
        if unread_only:
            q = ("is:unread " + q).strip()

        result = svc.users().messages().list(
            userId="me", labelIds=["INBOX"], q=q, maxResults=max_results
        ).execute()

        messages = result.get("messages", [])
        if not messages:
            return {"emails": [], "total": 0, "message": "No emails found."}

        emails = []
        for msg_meta in messages:
            msg = svc.users().messages().get(
                userId="me", id=msg_meta["id"], format="full"
            ).execute()
            headers = msg.get("payload", {}).get("headers", [])
            emails.append({
                "id": msg["id"],
                "from": _header(headers, "From"),
                "to": _header(headers, "To"),
                "subject": _header(headers, "Subject"),
                "date": _header(headers, "Date"),
                "snippet": msg.get("snippet", ""),
                "body": _decode_body(msg.get("payload", {})),
                "unread": "UNREAD" in msg.get("labelIds", []),
            })

        return {"emails": emails, "total": len(emails)}
    except Exception as e:
        return {"error": str(e)}


def send_email(to: str, subject: str, body: str, cc: str = "") -> dict[str, Any]:
    """Send an email via Gmail."""
    try:
        svc = _gmail()
        msg = MIMEMultipart("alternative")
        msg["To"] = to
        msg["Subject"] = subject
        if cc:
            msg["Cc"] = cc
        msg.attach(MIMEText(body, "plain"))

        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
        result = svc.users().messages().send(userId="me", body={"raw": raw}).execute()
        return {"success": True, "message_id": result["id"], "message": f"Email sent to {to}."}
    except Exception as e:
        return {"error": str(e)}


def reply_to_email(message_id: str, body: str) -> dict[str, Any]:
    """Reply to an existing email thread."""
    try:
        svc = _gmail()
        original = svc.users().messages().get(
            userId="me", id=message_id, format="full"
        ).execute()
        headers = original.get("payload", {}).get("headers", [])

        to = _header(headers, "From")
        subject = _header(headers, "Subject")
        if not subject.startswith("Re:"):
            subject = "Re: " + subject
        thread_id = original["threadId"]

        msg = MIMEMultipart("alternative")
        msg["To"] = to
        msg["Subject"] = subject
        msg["In-Reply-To"] = _header(headers, "Message-ID")
        msg["References"] = _header(headers, "Message-ID")
        msg.attach(MIMEText(body, "plain"))

        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
        result = svc.users().messages().send(
            userId="me", body={"raw": raw, "threadId": thread_id}
        ).execute()
        return {"success": True, "message_id": result["id"], "message": f"Reply sent to {to}."}
    except Exception as e:
        return {"error": str(e)}
