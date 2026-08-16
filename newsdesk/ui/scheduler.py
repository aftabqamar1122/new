"""Wall-clock scheduler for unattended collection runs.

Slots are plain ``HH:MM`` strings in local time. Times that have already passed
when the app starts are marked as done for today, so launching the app at 18:05
does not immediately fire the 07:00 and 12:00 runs.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta

from PySide6.QtCore import QObject, QTimer, Signal

TICK_MS = 20_000


def parse_slot(value: str) -> time | None:
    try:
        hour, minute = value.strip().split(":")
        return time(int(hour), int(minute))
    except (ValueError, AttributeError):
        return None


class Scheduler(QObject):
    due = Signal(str)  # the "HH:MM" slot that fired

    def __init__(self, parent=None):
        super().__init__(parent)
        self._times: list[str] = []
        self._enabled = False
        self._fired: dict[str, date] = {}
        self._timer = QTimer(self)
        self._timer.setInterval(TICK_MS)
        self._timer.timeout.connect(self._tick)
        self._timer.start()

    def configure(self, enabled: bool, times: list[str]) -> None:
        """Apply settings; past slots are suppressed for the rest of today."""
        self._enabled = bool(enabled)
        self._times = [t for t in (times or []) if parse_slot(t)]
        now = datetime.now()
        for slot in self._times:
            slot_time = parse_slot(slot)
            if slot_time and datetime.combine(now.date(), slot_time) <= now:
                self._fired[slot] = now.date()

    def next_run(self) -> datetime | None:
        if not self._enabled or not self._times:
            return None
        now = datetime.now()
        candidates: list[datetime] = []
        for slot in self._times:
            slot_time = parse_slot(slot)
            if not slot_time:
                continue
            today = datetime.combine(now.date(), slot_time)
            if today > now and self._fired.get(slot) != now.date():
                candidates.append(today)
            else:
                candidates.append(datetime.combine(now.date() + timedelta(days=1), slot_time))
        return min(candidates) if candidates else None

    def _tick(self) -> None:
        if not self._enabled:
            return
        now = datetime.now()
        for slot in list(self._times):
            slot_time = parse_slot(slot)
            if not slot_time:
                continue
            scheduled = datetime.combine(now.date(), slot_time)
            if scheduled <= now and self._fired.get(slot) != now.date():
                self._fired[slot] = now.date()
                self.due.emit(slot)
