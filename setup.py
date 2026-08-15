"""Setup script — interactive first-time configuration."""

import os
import sys
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt, Confirm

console = Console()


def check_anthropic_key():
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    if key:
        console.print(f"[green]✓[/] ANTHROPIC_API_KEY found ({key[:8]}...)")
        return True

    console.print("[yellow]![/] ANTHROPIC_API_KEY not set.")
    console.print("Get your key from: [link]https://console.anthropic.com[/]")
    key = Prompt.ask("  Paste your Anthropic API key (or press Enter to skip)")
    if key:
        shell_rc = Path.home() / ".bashrc"
        with open(shell_rc, "a") as f:
            f.write(f'\nexport ANTHROPIC_API_KEY="{key}"\n')
        console.print(f"[green]✓[/] Key saved to {shell_rc}. Run: [bold]source ~/.bashrc[/]")
    return bool(key)


def check_google_credentials():
    creds_file = Path("credentials.json")
    if creds_file.exists():
        console.print("[green]✓[/] credentials.json found.")
        return True

    console.print("[yellow]![/] credentials.json not found.")
    console.print(
        Panel(
            "[bold]How to get Google credentials:[/]\n\n"
            "1. Go to [link]https://console.cloud.google.com[/]\n"
            "2. Create a project (or select existing)\n"
            "3. Enable [bold]Gmail API[/] and [bold]Google Calendar API[/]\n"
            "4. Go to APIs & Services → Credentials\n"
            "5. Create OAuth 2.0 Client ID → Desktop App\n"
            "6. Download the JSON and save it as [bold]credentials.json[/] in this folder\n\n"
            "Then re-run [bold]python setup.py[/]",
            title="Google API Setup",
            border_style="yellow",
        )
    )
    return False


def main():
    console.print("\n[bold cyan]Daily Activities Agent — Setup[/]\n")

    ok_api = check_anthropic_key()
    ok_google = check_google_credentials()

    console.print()
    if ok_api and ok_google:
        console.print("[bold green]✓ Setup complete![/] Run the agent with:")
        console.print("  [bold]python main.py[/]\n")
        console.print("On first run the agent will open your browser to authorize Google access.")
    else:
        console.print("[yellow]Complete the steps above, then re-run:[/] [bold]python setup.py[/]")


if __name__ == "__main__":
    main()
