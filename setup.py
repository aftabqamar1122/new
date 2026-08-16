"""Setup script — interactive first-time configuration."""

import os
import sys
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt, Confirm

console = Console()


PROVIDERS = {
    "1": ("deepseek", "DEEPSEEK_API_KEY", "https://platform.deepseek.com/api_keys"),
    "2": ("anthropic", "ANTHROPIC_API_KEY", "https://console.anthropic.com"),
}


def check_api_key():
    """Confirm a model provider key is available, offering to save one if not."""
    for _, (provider, env_var, _url) in PROVIDERS.items():
        key = os.environ.get(env_var, "")
        if key:
            console.print(f"[green]✓[/] {env_var} found ({key[:8]}...) — using {provider}.")
            return True

    console.print("[yellow]![/] No model API key set. You need one of:")
    console.print("    [bold]1[/] DeepSeek  — https://platform.deepseek.com/api_keys")
    console.print("    [bold]2[/] Anthropic — https://console.anthropic.com")
    choice = Prompt.ask("  Which will you use?", choices=["1", "2"], default="1")
    provider, env_var, url = PROVIDERS[choice]

    console.print(f"  Get your key from: [link]{url}[/]")
    key = Prompt.ask(f"  Paste your {provider} API key (or press Enter to skip)")
    if key:
        shell_rc = Path.home() / ".bashrc"
        with open(shell_rc, "a") as f:
            f.write(f'\nexport {env_var}="{key}"\n')
        console.print(f"[green]✓[/] Key saved to {shell_rc}. Run: [bold]source ~/.bashrc[/]")
    return bool(key)


def check_google_credentials():
    creds_file = Path("credentials.json")
    if creds_file.exists():
        console.print("[green]✓[/] credentials.json found — email and calendar tools enabled.")
        return True

    console.print("[yellow]![/] credentials.json not found (optional — email/calendar only).")
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
    console.print("\n[bold cyan]Personal Agent — Setup[/]\n")

    ok_api = check_api_key()
    ok_google = check_google_credentials()

    console.print()
    if not ok_api:
        console.print("[yellow]Set a model API key, then re-run:[/] [bold]python setup.py[/]")
        return

    console.print("[bold green]✓ Ready.[/] Talk to your agent with:")
    console.print("  [bold]python chat.py[/]\n")
    if ok_google:
        console.print("Email and calendar tools are enabled — [bold]python main.py[/] runs the daily assistant.")
        console.print("On first use the agent will open your browser to authorize Google access.")
    else:
        console.print("[dim]Email and calendar are optional; add credentials.json above to enable them.[/]")


if __name__ == "__main__":
    main()
