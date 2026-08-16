"""Small logging helper shared by the GUI and the headless CLI.

A log entry is ``(level, message)``; sinks decide what to do with it. Everything
is also appended to ``~/.newsdesk/newsdesk.log`` so a scheduled run that
happened while the window was closed can still be inspected afterwards.
"""

from __future__ import annotations

import threading
from datetime import datetime
from pathlib import Path
from typing import Callable

from .config import LOG_PATH

LEVELS = ("debug", "info", "warn", "error", "success")
MAX_LOG_BYTES = 1_000_000


class LogBus:
    """Thread-safe fan-out of log lines to registered sinks plus a log file."""

    def __init__(self, path: Path | None = None, to_file: bool = True):
        self.path = path or LOG_PATH
        self.to_file = to_file
        self._sinks: list[Callable[[str, str, datetime], None]] = []
        self._lock = threading.Lock()

    def subscribe(self, sink: Callable[[str, str, datetime], None]) -> None:
        with self._lock:
            self._sinks.append(sink)

    def log(self, level: str, message: str) -> None:
        stamp = datetime.now()
        with self._lock:
            sinks = list(self._sinks)
        for sink in sinks:
            try:
                sink(level, message, stamp)
            except Exception:  # noqa: BLE001 - a bad sink must not break a run
                pass
        if self.to_file:
            self._write(level, message, stamp)

    def _write(self, level: str, message: str, stamp: datetime) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            if self.path.exists() and self.path.stat().st_size > MAX_LOG_BYTES:
                self.path.replace(self.path.with_suffix(".log.1"))
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(
                    f"{stamp.strftime('%Y-%m-%d %H:%M:%S')} [{level.upper():7}] {message}\n"
                )
        except OSError:
            pass

    def callback(self) -> Callable[[str, str], None]:
        """Adapter matching the ``log(level, message)`` signature used by core code."""
        return self.log


def console_sink(level: str, message: str, stamp: datetime) -> None:
    print(f"{stamp.strftime('%H:%M:%S')} [{level}] {message}", flush=True)
