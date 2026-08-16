"""Background collection thread so the UI never blocks on network or AI calls."""

from __future__ import annotations

from PySide6.QtCore import QThread, Signal

from ..config import Config
from ..pipeline import run


class CollectWorker(QThread):
    log_line = Signal(str, str)          # level, message
    progress = Signal(int, str)          # percent, stage
    report_ready = Signal(object)        # Report
    crashed = Signal(str)

    def __init__(self, config: Config, parent=None):
        super().__init__(parent)
        self._config = config
        self._cancel = False

    def cancel(self) -> None:
        self._cancel = True
        self.log_line.emit("warn", "Cancellation requested — finishing current stage…")

    def run(self) -> None:  # noqa: D102 - QThread entry point
        try:
            report = run(
                self._config,
                log=lambda level, message: self.log_line.emit(level, message),
                progress=lambda percent, stage: self.progress.emit(percent, stage),
                cancelled=lambda: self._cancel,
            )
            self.report_ready.emit(report)
        except Exception as exc:  # noqa: BLE001 - surface, never kill the app
            self.crashed.emit(f"{type(exc).__name__}: {exc}")
