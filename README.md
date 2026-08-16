# Personal AI Agent

Your own AI companion in the terminal. It talks with you, remembers what you tell it between
sessions, keeps your tasks, and — if you connect Google — handles your email and calendar too.

Two ways in:

| | |
|---|---|
| **`python chat.py`** | **Your personal agent.** Conversation with long-term memory. Needs only an Anthropic API key. |
| `python main.py` | The daily-activities assistant: email, calendar, tasks, morning brief. Needs Google credentials. |

## Talk to your agent

### 1. Install and run

```bash
pip install -r requirements.txt
export ANTHROPIC_API_KEY=your_key_here
python chat.py
```

That's it — no Google setup needed for the conversational agent.

```
Ava · your personal agent
We haven't met yet. Tell me a bit about yourself and I'll remember it.

You: I'm Aftab, I'm a civil engineer working on the Almeria project
Ava  Nice to meet you, Aftab. What's the Almeria project — infrastructure, buildings?

You: remind me to send the manpower report Thursday
Ava  Added it for Thursday. Want it flagged high priority?
```

Come back tomorrow and it still knows who you are.

### 2. Options

```bash
python chat.py --name Max          # name your agent something else
python chat.py --user Aftab        # tell it what to call you
python chat.py --fresh             # don't reload the last conversation
python chat.py "how's my week?"    # one-shot: ask and exit
```

In-chat commands: `memories` (see everything it knows) · `new` (fresh conversation, keeps memory) ·
`forget-all` (erase the transcript, keeps memory) · `clear` · `help` · `exit`

### 3. What it remembers

Facts it picks up — your name, work, preferences, people, projects — are stored in
`~/.personal_agent/memory.db` (SQLite, on your machine only) and loaded into every conversation.
Ask it to forget something and it will delete the entry. Run `memories` to see the whole list.

Your last 20 turns are reloaded at startup, so a conversation can span days.

## Email and calendar (optional)

The personal agent picks up Gmail and Calendar tools automatically once Google credentials exist —
no code changes, no flags. Until then it simply doesn't offer them.

```bash
python setup.py
```

Follow the on-screen instructions to:
- Set your `ANTHROPIC_API_KEY`
- Download `credentials.json` from Google Cloud Console

On first use a browser window opens for Google OAuth2 authorization. After approving, the token is
saved to `~/.daily_agent/token.json` — you only need to authorize once.

`python main.py` runs the original task-focused assistant against the same Google setup.

## Prerequisites

- Python 3.11+
- An [Anthropic API key](https://console.anthropic.com)
- *Optional:* a Google Cloud project with Gmail API + Google Calendar API enabled

## Tests

```bash
python test_personal_agent.py
```

No API key or network needed — the Anthropic client is stubbed.

## Google API Setup (detailed)

1. Go to [Google Cloud Console](https://console.cloud.google.com)
2. Create a project → **APIs & Services** → **Enable APIs**
3. Enable **Gmail API** and **Google Calendar API**
4. **Credentials** → **Create Credentials** → **OAuth 2.0 Client IDs**
5. Application type: **Desktop app** → Download JSON
6. Save the downloaded file as `credentials.json` in this directory

## Usage Examples (`main.py`)

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

Commands: `clear` · `reset` · `help` · `exit`

## Project Structure

```
.
├── chat.py              # Personal agent CLI  ← start here
├── personal_agent.py    # Conversational agent: memory + tasks (+ Google if configured)
├── main.py              # Daily-activities CLI
├── agent.py             # Task-focused agent loop over the Google tools
├── tools/
│   ├── memory_tools.py  # Long-term memory (SQLite)
│   ├── task_tools.py    # Local task manager (SQLite)
│   ├── email_tools.py   # Gmail API wrappers
│   └── calendar_tools.py # Google Calendar API wrappers
├── auth/
│   └── google_auth.py   # Google OAuth2 helper
├── setup.py             # First-time setup wizard
├── test_personal_agent.py
└── requirements.txt
```

Local data, none of it leaves your machine except as context sent to the Anthropic API:

| Path | Contents |
|---|---|
| `~/.personal_agent/memory.db` | What the agent remembers about you + your chat log |
| `~/.daily_agent/tasks.db` | Tasks and reminders |
| `~/.daily_agent/token.json` | Google OAuth token |
