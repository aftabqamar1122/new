"""Entry point: GUI by default, or a headless one-shot run with ``--collect``."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import APP_NAME, __version__
from .config import CONFIG_PATH, Config
from .logbus import LogBus, console_sink


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="newsdesk",
        description=f"{APP_NAME} — automated military & financial news briefing.",
    )
    parser.add_argument(
        "--collect",
        action="store_true",
        help="run one collection headlessly, write the report files, and exit",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        help=f"path to the settings file (default: {CONFIG_PATH})",
    )
    parser.add_argument(
        "--provider",
        default=None,
        help="override the AI provider for this run (anthropic, openai, gemini, ollama, none)",
    )
    parser.add_argument("--version", action="version", version=f"{APP_NAME} {__version__}")
    return parser.parse_args(argv)


def run_headless(config: Config) -> int:
    from .pipeline import run

    logbus = LogBus()
    logbus.subscribe(console_sink)
    report = run(config, logbus.callback())
    counts = report.counts
    print(
        f"\n{report.title()}\n"
        f"{counts['total']} stories — {counts['high']} high, "
        f"{counts['medium']} medium, {counts['low']} low"
    )
    for path in report.files:
        print(f"  wrote {path}")
    return 0 if report.articles else 1


def run_gui(config: Config) -> int:
    try:
        from PySide6.QtCore import QTimer
        from PySide6.QtWidgets import QApplication, QSystemTrayIcon
    except ImportError:
        print(
            "PySide6 is required for the NewsDesk window.\n"
            "Install it with:  pip install PySide6\n"
            "Or run a one-off collection without the GUI:  python -m newsdesk --collect",
            file=sys.stderr,
        )
        return 2

    from .ui.main_window import MainWindow
    from .ui.theme import apply_theme, app_icon

    app = QApplication(sys.argv[:1])
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(APP_NAME)
    app.setApplicationVersion(__version__)
    apply_theme(app)
    app.setWindowIcon(app_icon())

    logbus = LogBus()
    window = MainWindow(config, logbus)

    tray_ok = QSystemTrayIcon.isSystemTrayAvailable()
    keep_alive = tray_ok and bool(config.get("ui.minimize_to_tray", True))
    app.setQuitOnLastWindowClosed(not keep_alive)
    if not tray_ok:
        logbus.log(
            "warn",
            "No system tray on this desktop — the app will exit when the window closes",
        )

    if config.get("ui.start_minimized", False) and tray_ok:
        logbus.log("info", "Started minimised to the system tray")
    else:
        window.show()

    if config.get("schedule.run_on_start", False):
        QTimer.singleShot(1500, window.start_collection)

    return app.exec()


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    config = Config.load(args.config)
    if args.provider:
        config.set("ai.provider", args.provider)
        config.set("ai.enabled", args.provider != "none")
    if not (args.config or CONFIG_PATH.exists()):
        config.save()  # materialise defaults on first launch
    return run_headless(config) if args.collect else run_gui(config)


if __name__ == "__main__":
    raise SystemExit(main())
