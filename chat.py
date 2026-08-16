#!/usr/bin/env python3
"""Talk to your personal agent.

    export DEEPSEEK_API_KEY=sk-...
    python chat.py
"""

import argparse
import sys

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.prompt import Prompt
from rich.theme import Theme

from llm import ENV_KEYS, MissingAPIKey, build_backend
from personal_agent import PersonalAgent
from tools import memory_tools

console = Console(theme=Theme({
    "you": "bold cyan",
    "agent": "bold magenta",
    "system": "dim",
    "error": "bold red",
}))

HELP = """
**Just talk to me.** Tell me about your day, think out loud, ask me things.
I remember what you tell me between sessions.

Some things I can do:
- *"I'm Aftab, I work as a civil engineer in Almeria"* → I'll remember it
- *"What do you know about me?"*
- *"Remind me to call the supplier on Thursday"*
- *"What's on my plate?"*
- *"Forget that I said I like early meetings"*

**Commands:** `memories` · `forget-all` · `new` · `clear` · `help` · `exit`
"""


def _stream(text: str) -> None:
    """Print a streamed chunk verbatim — no markup parsing, no re-wrapping."""
    console.print(text, end="", markup=False, highlight=False, soft_wrap=True)


def _greeting(agent: PersonalAgent) -> str:
    counts = memory_tools.stats()
    if agent.resumed_turns:
        return f"Picking up where we left off — {counts['facts']} things remembered about you."
    if counts["facts"]:
        return f"Good to see you again. I remember {counts['facts']} things about you."
    return "We haven't met yet. Tell me a bit about yourself and I'll remember it."


def _show_memories() -> None:
    result = memory_tools.recall(limit=100)
    rows = result.get("memories", [])
    if not rows:
        console.print("[system]I don't know anything about you yet.[/]")
        return
    lines = "\n".join(f"`#{r['id']}` **{r['category']}** — {r['content']}" for r in rows)
    console.print(Panel(Markdown(lines), title=f"What I remember ({len(rows)})", border_style="magenta"))


def run(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Chat with your personal agent.")
    parser.add_argument("--name", default="Ava", help="What to call your agent (default: Ava)")
    parser.add_argument("--user", default="", help="What the agent should call you")
    parser.add_argument("--fresh", action="store_true", help="Start without reloading the last conversation")
    parser.add_argument(
        "--provider",
        default="auto",
        choices=["auto", *ENV_KEYS],
        help="Which model provider to use (default: whichever API key is set)",
    )
    parser.add_argument("--model", default="", help="Override the model, e.g. deepseek-reasoner")
    parser.add_argument("--no-stream", action="store_true", help="Wait for the full reply instead of streaming")
    parser.add_argument("message", nargs="*", help="Say one thing and exit, instead of chatting")
    args = parser.parse_args(argv)

    try:
        backend = build_backend(provider=args.provider, model=args.model, stream=not args.no_stream)
    except (MissingAPIKey, ValueError) as e:
        console.print(f"[error]{e}[/]")
        return 1
    except RuntimeError as e:  # missing SDK package
        console.print(f"[error]{e}[/]")
        return 1

    agent = PersonalAgent(backend=backend, agent_name=args.name, user_name=args.user, resume=not args.fresh)

    # One-shot mode: `python chat.py "how's my week looking?"`
    if args.message:
        agent.chat(" ".join(args.message), on_text=_stream)
        console.print()
        return 0

    console.print(f"\n[agent]{args.name}[/] [system]· your personal agent · {backend.provider}/{backend.model}[/]")
    console.print(f"[system]{_greeting(agent)}[/]")
    console.print("[system]Type [bold]help[/] for ideas, [bold]exit[/] to leave.[/]\n")

    while True:
        try:
            user_input = Prompt.ask("[you]You[/]").strip()
        except (KeyboardInterrupt, EOFError):
            console.print("\n[system]Talk soon.[/]")
            return 0

        if not user_input:
            continue

        cmd = user_input.lower()
        if cmd in ("exit", "quit", "bye"):
            console.print("[system]Talk soon.[/]")
            return 0
        if cmd == "clear":
            console.clear()
            continue
        if cmd in ("help", "?"):
            console.print(Panel(Markdown(HELP), border_style="dim"))
            continue
        if cmd == "memories":
            _show_memories()
            continue
        if cmd == "new":
            agent.reset()
            console.print("[system]Fresh conversation. I still remember what I know about you.[/]")
            continue
        if cmd == "forget-all":
            confirm = Prompt.ask("[system]Erase the conversation log? (facts are kept)[/]", choices=["y", "n"], default="n")
            if confirm == "y":
                agent.reset(forget_history=True)
                console.print("[system]Conversation log erased.[/]")
            continue

        console.print(f"\n[agent]{args.name}[/]  ", end="")
        try:
            agent.chat(user_input, on_text=_stream)
        except KeyboardInterrupt:
            console.print("\n[system](stopped)[/]")
            continue
        except Exception as e:
            console.print(f"\n[error]Something went wrong:[/] {e}")
            continue
        console.print("\n")


if __name__ == "__main__":
    sys.exit(run())
