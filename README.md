# Daily Activities AI Agent

A personal AI assistant that manages your emails, calendar, tasks, and morning brief — all from a terminal chat interface.

> **Also in this repo:** [**NewsDesk**](NEWSDESK.md) — a dark-themed desktop app that
> collects the day's military and financial news from BBC, Reuters, CNN, CNBC, the NYT
> and others, ranks it by importance, summarises it with the AI provider of your choice,
> and exports a Markdown + HTML briefing on a schedule.
> Run it with `python newsdesk_app.py`.

## Features

| Capability | What it does |
|---|---|
| 📧 Email | Read inbox, search, send emails, reply to threads |
| 📅 Calendar | View events, create meetings (with Google Meet), delete events |
| ✅ Tasks | Add, list, complete, update, delete tasks with priorities & due dates |
| 🌅 Morning Brief | Daily summary of unread emails, today's events, and pending tasks |

## Prerequisites

- Python 3.11+
- An [Anthropic API key](https://console.anthropic.com)
- A Google Cloud project with Gmail API + Google Calendar API enabled

## Quick Start

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Set up credentials

```bash
python setup.py
```

Follow the on-screen instructions to:
- Set your `ANTHROPIC_API_KEY`
- Download `credentials.json` from Google Cloud Console

### 3. Run the agent

```bash
export ANTHROPIC_API_KEY=your_key_here
python main.py
```

On first run, a browser window will open for Google OAuth2 authorization. After approving, the token is saved to `~/.daily_agent/token.json` — you only need to authorize once.

## Google API Setup (detailed)

1. Go to [Google Cloud Console](https://console.cloud.google.com)
2. Create a project → **APIs & Services** → **Enable APIs**
3. Enable **Gmail API** and **Google Calendar API**
4. **Credentials** → **Create Credentials** → **OAuth 2.0 Client IDs**
5. Application type: **Desktop app** → Download JSON
6. Save the downloaded file as `credentials.json` in this directory

## Usage Examples

```
You: Good morning
Agent: Good morning! Here's your daily brief for Monday, August 15...
       📧 3 unread emails  📅 2 meetings today  ✅ 4 pending tasks

You: Show my unread emails
You: Reply to the email from John about the budget
You: What's on my calendar today?
You: Schedule a team sync tomorrow at 2pm for 30 minutes
You: Add a high-priority task: prepare Q3 report, due August 20
You: Show my pending tasks
You: Mark task #2 as done
```

## Commands

| Command | Action |
|---|---|
| `clear` | Clear the terminal |
| `reset` | Clear conversation history |
| `help` | Show quick reference |
| `exit` / `quit` | Exit the agent |

## Project Structure

```
.
├── main.py              # CLI entry point
├── agent.py             # Anthropic tool-use agent loop
├── tools/
│   ├── email_tools.py   # Gmail API wrappers
│   ├── calendar_tools.py # Google Calendar API wrappers
│   └── task_tools.py    # Local SQLite task manager
├── auth/
│   └── google_auth.py   # Google OAuth2 helper
├── setup.py             # First-time setup wizard
└── requirements.txt
```

Tasks are stored locally in `~/.daily_agent/tasks.db` (SQLite).
Google OAuth token is stored in `~/.daily_agent/token.json`.
