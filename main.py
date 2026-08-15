#!/usr/bin/env python3
"""Daily Activities AI Agent — CLI entry point."""

import os
import sys

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.prompt import Prompt
from rich.text import Text
from rich.theme import Theme

from agent import DailyAgent

THEME = Theme({
    "user": "bold cyan",
    "agent": "bold green",
    "system": "dim yellow",
    "error": "bold red",
})

console = Console(theme=THEME)

BANNER = """
[bold cyan]╔══════════════════════════════════════╗[/]
[bold cyan]║   Daily Activities AI Agent  🤖      ║[/]
[bold cyan]╚══════════════════════════════════════╝[/]
[dim]Commands: [bold]clear[/] · [bold]reset[/] · [bold]exit[/][/]
[dim]Start with: [italic]"Good morning"[/] for your daily brief[/]
"""

HELP_TEXT = """
**What I can do:**

📧 **Email**
- "Show my unread emails"
- "Send an email to john@example.com about the project update"
- "Reply to the last email from Sarah"
- "Search for emails from my boss"

📅 **Calendar**
- "What's on my calendar today?"
- "Show my schedule for this week"
- "Schedule a meeting with team@co.com tomorrow at 3pm for 1 hour"
- "Delete my 2pm event"

✅ **Tasks**
- "Add a task: review the Q3 report by Friday"
- "Show my pending tasks"
- "Mark task #3 as done"
- "Add a high-priority reminder to call the dentist"

🌅 **Morning Brief**
- "Good morning" or "Give me my morning brief"
"""


def run():
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        console.print("[error]Error:[/] ANTHROPIC_API_KEY environment variable not set.", style="error")
        console.print("Run: [bold]export ANTHROPIC_API_KEY=your_key_here[/]")
        sys.exit(1)

    console.print(BANNER)
    console.print(Panel(Markdown(HELP_TEXT), title="Quick Reference", border_style="dim"))

    agent = DailyAgent(api_key=api_key)

    while True:
        try:
            user_input = Prompt.ask("\n[bold cyan]You[/]").strip()
        except (KeyboardInterrupt, EOFError):
            console.print("\n[system]Goodbye! Have a productive day.[/]")
            break

        if not user_input:
            continue

        cmd = user_input.lower()
        if cmd in ("exit", "quit", "bye"):
            console.print("[system]Goodbye! Have a productive day.[/]")
            break
        if cmd == "clear":
            console.clear()
            console.print(BANNER)
            continue
        if cmd == "reset":
            agent.reset()
            console.print("[system]Conversation history cleared.[/]")
            continue
        if cmd in ("help", "?"):
            console.print(Panel(Markdown(HELP_TEXT), title="Quick Reference", border_style="dim"))
            continue

        with console.status("[bold green]Thinking...[/]", spinner="dots"):
            try:
                response = agent.chat(user_input)
            except Exception as e:
                console.print(f"\n[error]Error:[/] {e}")
                continue

        console.print("\n[bold green]Agent[/]")
        console.print(Panel(Markdown(response), border_style="green", padding=(0, 1)))


if __name__ == "__main__":
    run()
