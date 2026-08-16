"""Main application window: story list, AI brief and activity log."""

from __future__ import annotations

import json
from datetime import datetime

from PySide6.QtCore import QUrl, Qt
from PySide6.QtGui import QAction, QColor, QDesktopServices, QFont
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QSystemTrayIcon,
    QTableWidget,
    QTableWidgetItem,
    QTextBrowser,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from .. import APP_NAME, __version__
from ..config import STATE_PATH, Config
from ..export import markdown_to_html, write_reports
from ..logbus import LogBus
from ..models import Report
from . import theme
from .scheduler import Scheduler
from .settings_dialog import SettingsDialog
from .worker import CollectWorker

COLUMNS = ["Time", "Importance", "Category", "Region", "Source", "Headline"]
MAX_LOG_LINES = 2000


class SortableItem(QTableWidgetItem):
    """Table cell that sorts on a hidden key rather than its display text."""

    SORT_ROLE = Qt.UserRole + 1

    def __init__(self, text: str, sort_key):
        super().__init__(text)
        self.setData(self.SORT_ROLE, sort_key)
        self.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)

    def __lt__(self, other: QTableWidgetItem) -> bool:  # noqa: D105
        mine = self.data(self.SORT_ROLE)
        theirs = other.data(self.SORT_ROLE)
        if mine is None or theirs is None:
            return super().__lt__(other)
        return mine < theirs


class MainWindow(QMainWindow):
    def __init__(self, config: Config, logbus: LogBus):
        super().__init__()
        self.config = config
        self.logbus = logbus
        self.report: Report | None = None
        self.worker: CollectWorker | None = None
        self._force_quit = False

        self.setWindowTitle(f"{APP_NAME} — military & financial brief")
        self.setWindowIcon(theme.app_icon())
        self.resize(1360, 840)

        self._build_toolbar()
        self._build_body()
        self._build_status_bar()
        self._build_tray()

        self.logbus.subscribe(self._on_log)

        self.scheduler = Scheduler(self)
        self.scheduler.due.connect(self._on_schedule_due)
        self._apply_schedule()

        self._load_last_report()
        self.logbus.log("info", f"{APP_NAME} {__version__} ready")

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    def _build_toolbar(self) -> None:
        toolbar = QToolBar("Main")
        toolbar.setMovable(False)
        self.addToolBar(toolbar)

        self.action_collect = QAction("⟳  Collect now", self)
        self.action_collect.triggered.connect(self.start_collection)
        toolbar.addAction(self.action_collect)

        self.action_cancel = QAction("■  Stop", self)
        self.action_cancel.triggered.connect(self._cancel_collection)
        self.action_cancel.setEnabled(False)
        toolbar.addAction(self.action_cancel)

        toolbar.addSeparator()

        self.action_export = QAction("↧  Export report", self)
        self.action_export.triggered.connect(self.export_report)
        self.action_export.setEnabled(False)
        toolbar.addAction(self.action_export)

        self.action_folder = QAction("🗀  Open folder", self)
        self.action_folder.triggered.connect(self.open_report_folder)
        toolbar.addAction(self.action_folder)

        toolbar.addSeparator()
        self.action_settings = QAction("⚙  Settings", self)
        self.action_settings.triggered.connect(self.open_settings)
        toolbar.addAction(self.action_settings)

        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        toolbar.addWidget(spacer)

        self.provider_label = QLabel()
        self.provider_label.setStyleSheet(f"color: {theme.MUTED}; padding-right: 10px;")
        toolbar.addWidget(self.provider_label)
        self._refresh_provider_label()

    def _build_body(self) -> None:
        splitter = QSplitter(Qt.Horizontal)

        # --- left: filters + story table -------------------------------
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(10, 10, 6, 10)
        left_layout.setSpacing(8)

        filter_row = QHBoxLayout()
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Search headlines, sources, regions…")
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.textChanged.connect(self._apply_filters)

        self.category_filter = QComboBox()
        self.category_filter.addItems(["All categories", "Military", "Financial", "Other"])
        self.category_filter.currentIndexChanged.connect(self._apply_filters)

        self.importance_filter = QComboBox()
        self.importance_filter.addItems(["All importance", "High", "Medium", "Low"])
        self.importance_filter.currentIndexChanged.connect(self._apply_filters)

        self.region_filter = QComboBox()
        self.region_filter.addItem("All regions")
        self.region_filter.currentIndexChanged.connect(self._apply_filters)

        filter_row.addWidget(self.search_edit, 1)
        filter_row.addWidget(self.category_filter)
        filter_row.addWidget(self.importance_filter)
        filter_row.addWidget(self.region_filter)
        left_layout.addLayout(filter_row)

        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels(COLUMNS)
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSortingEnabled(True)
        self.table.setWordWrap(False)
        self.table.doubleClicked.connect(self._open_selected_link)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._show_table_menu)

        header = self.table.horizontalHeader()
        for index in range(len(COLUMNS) - 1):
            header.setSectionResizeMode(index, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(len(COLUMNS) - 1, QHeaderView.Stretch)
        left_layout.addWidget(self.table, 1)

        self.count_label = QLabel("No stories yet — press “Collect now”.")
        self.count_label.setStyleSheet(f"color: {theme.MUTED};")
        left_layout.addWidget(self.count_label)

        # --- right: brief + log ----------------------------------------
        right = QSplitter(Qt.Vertical)

        brief_panel = QWidget()
        brief_layout = QVBoxLayout(brief_panel)
        brief_layout.setContentsMargins(6, 10, 10, 4)
        brief_layout.setSpacing(6)

        brief_header = QHBoxLayout()
        title = QLabel("AI brief")
        title.setStyleSheet(f"color: {theme.MUTED}; font-weight: 600;")
        self.copy_brief_button = QPushButton("Copy")
        self.copy_brief_button.setFixedWidth(70)
        self.copy_brief_button.clicked.connect(self._copy_brief)
        brief_header.addWidget(title)
        brief_header.addStretch(1)
        brief_header.addWidget(self.copy_brief_button)
        brief_layout.addLayout(brief_header)

        self.brief_view = QTextBrowser()
        self.brief_view.setOpenExternalLinks(True)
        self.brief_view.setStyleSheet(
            f"QTextBrowser {{ background: {theme.PANEL}; border: 1px solid {theme.LINE};"
            f" border-radius: 8px; padding: 10px; }}"
        )
        self.brief_view.setHtml(_placeholder_html())
        brief_layout.addWidget(self.brief_view, 1)
        right.addWidget(brief_panel)

        log_panel = QWidget()
        log_layout = QVBoxLayout(log_panel)
        log_layout.setContentsMargins(6, 4, 10, 10)
        log_layout.setSpacing(6)

        log_header = QHBoxLayout()
        log_title = QLabel("Activity log")
        log_title.setStyleSheet(f"color: {theme.MUTED}; font-weight: 600;")
        clear_button = QPushButton("Clear")
        clear_button.setFixedWidth(70)
        clear_button.clicked.connect(lambda: self.log_view.clear())
        log_header.addWidget(log_title)
        log_header.addStretch(1)
        log_header.addWidget(clear_button)
        log_layout.addLayout(log_header)

        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(MAX_LOG_LINES)
        self.log_view.setFont(theme.mono_font(11))
        self.log_view.setLineWrapMode(QPlainTextEdit.NoWrap)
        log_layout.addWidget(self.log_view, 1)
        right.addWidget(log_panel)
        right.setSizes([460, 340])

        splitter.addWidget(left)
        splitter.addWidget(right)
        splitter.setSizes([820, 540])
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        self.setCentralWidget(splitter)

    def _build_status_bar(self) -> None:
        bar = self.statusBar()
        self.status_label = QLabel("Idle")
        self.next_run_label = QLabel("")
        self.progress = QProgressBar()
        self.progress.setFixedWidth(190)
        self.progress.setVisible(False)
        bar.addWidget(self.status_label, 1)
        bar.addPermanentWidget(self.next_run_label)
        bar.addPermanentWidget(self.progress)

    def _build_tray(self) -> None:
        self.tray = QSystemTrayIcon(theme.app_icon(), self)
        self.tray.setToolTip(f"{APP_NAME} — idle")
        menu = QMenu()
        show_action = menu.addAction("Show window")
        show_action.triggered.connect(self._restore_window)
        collect_action = menu.addAction("Collect now")
        collect_action.triggered.connect(self.start_collection)
        menu.addSeparator()
        folder_action = menu.addAction("Open report folder")
        folder_action.triggered.connect(self.open_report_folder)
        menu.addSeparator()
        quit_action = menu.addAction("Quit NewsDesk")
        quit_action.triggered.connect(self.quit_app)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self._on_tray_activated)
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.tray.show()

    # ------------------------------------------------------------------
    # Collection
    # ------------------------------------------------------------------

    def start_collection(self) -> None:
        if self.worker and self.worker.isRunning():
            self.logbus.log("warn", "A collection is already running")
            return
        self.action_collect.setEnabled(False)
        self.action_cancel.setEnabled(True)
        self.progress.setVisible(True)
        self.progress.setValue(0)
        self.status_label.setText("Collecting…")
        self.tray.setToolTip(f"{APP_NAME} — collecting…")

        self.worker = CollectWorker(self.config, self)
        self.worker.log_line.connect(self.logbus.log)
        self.worker.progress.connect(self._on_progress)
        self.worker.report_ready.connect(self._on_report)
        self.worker.crashed.connect(self._on_crash)
        self.worker.finished.connect(self._on_worker_finished)
        self.worker.start()

    def _cancel_collection(self) -> None:
        if self.worker and self.worker.isRunning():
            self.worker.cancel()
            self.action_cancel.setEnabled(False)

    def _on_progress(self, percent: int, stage: str) -> None:
        self.progress.setValue(percent)
        self.status_label.setText(stage)

    def _on_worker_finished(self) -> None:
        self.action_collect.setEnabled(True)
        self.action_cancel.setEnabled(False)
        self.progress.setVisible(False)
        self.tray.setToolTip(f"{APP_NAME} — idle")

    def _on_crash(self, message: str) -> None:
        self.logbus.log("error", f"Collection failed: {message}")
        self.status_label.setText("Failed — see log")

    def _on_report(self, report: Report) -> None:
        self.report = report
        self.populate(report)
        self.action_export.setEnabled(True)
        counts = report.counts
        stamp = report.generated_at.astimezone().strftime("%H:%M")
        self.status_label.setText(
            f"Last run {stamp} — {counts['total']} stories "
            f"({counts['high']} high) · {report.feeds_ok} feeds OK, "
            f"{report.feeds_failed} failed"
        )
        self._save_last_report(report)
        if self.config.get("ui.notify_on_complete", True) and self.tray.isVisible():
            self.tray.showMessage(
                f"{APP_NAME} — brief ready",
                f"{counts['total']} stories · {counts['high']} high importance",
                theme.app_icon(),
                6000,
            )

    # ------------------------------------------------------------------
    # Display
    # ------------------------------------------------------------------

    def populate(self, report: Report) -> None:
        self.brief_view.setHtml(_brief_html(report))

        regions = sorted({a.region for a in report.articles})
        current = self.region_filter.currentText()
        self.region_filter.blockSignals(True)
        self.region_filter.clear()
        self.region_filter.addItem("All regions")
        self.region_filter.addItems(regions)
        index = self.region_filter.findText(current)
        self.region_filter.setCurrentIndex(index if index >= 0 else 0)
        self.region_filter.blockSignals(False)

        self.table.setSortingEnabled(False)
        self.table.setRowCount(0)
        for article in report.articles:
            row = self.table.rowCount()
            self.table.insertRow(row)

            when = article.published_label()
            sort_time = article.published.timestamp() if article.published else 0.0
            cells = [
                SortableItem(when, sort_time),
                SortableItem(
                    article.importance.upper(),
                    {"high": 0, "medium": 1, "low": 2}.get(article.importance, 3),
                ),
                SortableItem(article.category.capitalize(), article.category),
                SortableItem(article.region, article.region),
                SortableItem(article.source, article.source),
                SortableItem(article.title, article.title.lower()),
            ]
            colour = QColor(theme.IMPORTANCE_COLORS.get(article.importance, theme.TEXT))
            cells[1].setForeground(colour)
            if article.importance == "high":
                font = QFont()
                font.setBold(True)
                cells[5].setFont(font)

            tooltip = "\n".join(
                part
                for part in (
                    article.title,
                    article.summary,
                    f"Score {article.score} — {', '.join(article.reasons) or 'baseline'}",
                    (
                        "Also reported by: "
                        + ", ".join(article.corroborating_sources)
                        if article.corroborating_sources
                        else ""
                    ),
                    article.link,
                )
                if part
            )
            for column, item in enumerate(cells):
                item.setToolTip(tooltip)
                if column == 0:
                    item.setData(Qt.UserRole, article.link)
                    item.setData(Qt.UserRole + 2, article.title)
                self.table.setItem(row, column, item)

        self.table.setSortingEnabled(True)
        self._apply_filters()

    def _apply_filters(self) -> None:
        needle = self.search_edit.text().strip().lower()
        category = self.category_filter.currentText()
        importance = self.importance_filter.currentText()
        region = self.region_filter.currentText()
        visible = 0

        for row in range(self.table.rowCount()):
            texts = [
                self.table.item(row, column).text()
                for column in range(self.table.columnCount())
            ]
            show = True
            if needle and needle not in " ".join(texts).lower():
                show = False
            if show and not category.startswith("All") and texts[2] != category:
                show = False
            if show and not importance.startswith("All") and texts[1] != importance.upper():
                show = False
            if show and not region.startswith("All") and texts[3] != region:
                show = False
            self.table.setRowHidden(row, not show)
            visible += int(show)

        total = self.table.rowCount()
        if total == 0:
            self.count_label.setText("No stories yet — press “Collect now”.")
        elif visible == total:
            self.count_label.setText(f"{total} stories — double-click to open a headline.")
        else:
            self.count_label.setText(f"Showing {visible} of {total} stories.")

    def _selected_link(self) -> tuple[str, str]:
        row = self.table.currentRow()
        if row < 0:
            return "", ""
        item = self.table.item(row, 0)
        if item is None:
            return "", ""
        return item.data(Qt.UserRole) or "", item.data(Qt.UserRole + 2) or ""

    def _open_selected_link(self) -> None:
        link, _ = self._selected_link()
        if link:
            QDesktopServices.openUrl(QUrl(link))
        else:
            self.logbus.log("warn", "That story has no link")

    def _show_table_menu(self, position) -> None:
        if self.table.currentRow() < 0:
            return
        menu = QMenu(self)
        menu.addAction("Open in browser", self._open_selected_link)
        menu.addAction("Copy link", lambda: self._copy(self._selected_link()[0]))
        menu.addAction("Copy headline", lambda: self._copy(self._selected_link()[1]))
        menu.exec(self.table.viewport().mapToGlobal(position))

    def _copy(self, text: str) -> None:
        if text:
            QApplication.clipboard().setText(text)
            self.logbus.log("info", "Copied to clipboard")

    def _copy_brief(self) -> None:
        if self.report and self.report.ai_summary:
            self._copy(self.report.ai_summary)

    def _on_log(self, level: str, message: str, stamp: datetime) -> None:
        colour = theme.LEVEL_COLORS.get(level, theme.TEXT)
        safe = (
            message.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        )
        self.log_view.appendHtml(
            f'<span style="color:{theme.MUTED}">{stamp.strftime("%H:%M:%S")}</span> '
            f'<span style="color:{colour}">{safe}</span>'
        )

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def export_report(self) -> None:
        if not self.report:
            return
        formats = list(self.config.get("export.formats", ["markdown", "html"])) or [
            "markdown",
            "html",
        ]
        try:
            paths = write_reports(self.report, self.config.export_dir(), formats)
        except OSError as exc:
            QMessageBox.critical(self, "Export failed", str(exc))
            return
        self.report.files = [str(p) for p in paths]
        for path in paths:
            self.logbus.log("success", f"Wrote {path}")
        self.status_label.setText(f"Exported {len(paths)} file(s)")

    def open_report_folder(self) -> None:
        directory = self.config.export_dir()
        try:
            directory.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            QMessageBox.warning(self, "Cannot open folder", str(exc))
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(directory)))

    def open_settings(self) -> None:
        dialog = SettingsDialog(self.config, self)
        if dialog.exec() != SettingsDialog.Accepted:
            return
        self.config.data = dialog.result_data()
        self.config.save()
        self.logbus.log("success", "Settings saved")
        self._refresh_provider_label()
        self._apply_schedule()

    def _refresh_provider_label(self) -> None:
        from ..ai import PROVIDER_LABELS

        name = self.config.provider_name()
        if not self.config.get("ai.enabled", True):
            label = "AI off"
        else:
            model = self.config.provider_config(name).get("model", "")
            label = f"{PROVIDER_LABELS.get(name, name)}"
            if model and name != "none":
                label += f" · {model}"
        self.provider_label.setText(label)

    def _apply_schedule(self) -> None:
        self.scheduler.configure(
            bool(self.config.get("schedule.enabled", True)),
            list(self.config.get("schedule.times", [])),
        )
        self._refresh_next_run()

    def _refresh_next_run(self) -> None:
        upcoming = self.scheduler.next_run()
        if upcoming:
            self.next_run_label.setText(
                f"Next run {upcoming.strftime('%a %H:%M')}   "
            )
        else:
            self.next_run_label.setText("Schedule off   ")

    def _on_schedule_due(self, slot: str) -> None:
        self.logbus.log("info", f"Scheduled run triggered ({slot})")
        self.start_collection()
        self._refresh_next_run()

    # ------------------------------------------------------------------
    # Persistence of the last report
    # ------------------------------------------------------------------

    def _save_last_report(self, report: Report) -> None:
        try:
            STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
            STATE_PATH.write_text(
                json.dumps(report.to_dict(), indent=1), encoding="utf-8"
            )
        except (OSError, TypeError, ValueError) as exc:
            self.logbus.log("warn", f"Could not cache last report: {exc}")

    def _load_last_report(self) -> None:
        if not STATE_PATH.exists():
            return
        try:
            report = Report.from_dict(json.loads(STATE_PATH.read_text(encoding="utf-8")))
        except (OSError, ValueError, TypeError) as exc:
            self.logbus.log("warn", f"Could not restore last report: {exc}")
            return
        self.report = report
        self.populate(report)
        self.action_export.setEnabled(True)
        self.status_label.setText(
            "Restored last report from "
            + report.generated_at.astimezone().strftime("%d %b %H:%M")
        )

    # ------------------------------------------------------------------
    # Window lifecycle
    # ------------------------------------------------------------------

    def _on_tray_activated(self, reason) -> None:
        if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick):
            self._restore_window()

    def _restore_window(self) -> None:
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def quit_app(self) -> None:
        self._force_quit = True
        self.close()
        QApplication.quit()

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt override
        keep_running = (
            self.config.get("ui.minimize_to_tray", True)
            and self.tray.isVisible()
            and not self._force_quit
        )
        if keep_running:
            event.ignore()
            self.hide()
            self.tray.showMessage(
                f"{APP_NAME} is still running",
                "Scheduled collection continues in the background. "
                "Quit from the tray menu to stop it.",
                theme.app_icon(),
                4000,
            )
            return

        if self.worker and self.worker.isRunning():
            self.worker.cancel()
            self.worker.wait(4000)
        event.accept()


# ----------------------------------------------------------------------
# Small HTML helpers for the brief pane
# ----------------------------------------------------------------------

def _base_css() -> str:
    return (
        f"body {{ color:{theme.TEXT}; font-family:-apple-system,'Segoe UI',Roboto,"
        f"Helvetica,Arial,sans-serif; font-size:13.5px; line-height:1.55; }}"
        f" h2 {{ font-size:14.5px; color:{theme.ACCENT}; margin:14px 0 6px; }}"
        f" h3 {{ font-size:13px; color:{theme.MUTED}; margin:12px 0 4px; }}"
        f" ul {{ margin:4px 0 4px 16px; padding-left:6px; }}"
        f" li {{ margin-bottom:5px; }}"
        f" a {{ color:{theme.ACCENT}; }}"
        f" .meta {{ color:{theme.MUTED}; font-size:12px; }}"
        f" hr {{ border:0; border-top:1px solid {theme.LINE}; }}"
    )


def _placeholder_html() -> str:
    return (
        f"<style>{_base_css()}</style>"
        f"<p class='meta'>No brief yet.</p>"
        f"<p>Press <b>Collect now</b> to pull the day's military and financial "
        f"headlines, rank them, and generate a brief.</p>"
        f"<p class='meta'>Configure providers, schedule times and feeds in "
        f"<b>Settings</b>.</p>"
    )


def _brief_html(report: Report) -> str:
    counts = report.counts
    header = (
        f"<p class='meta'>{report.generated_at.astimezone().strftime('%d %b %Y %H:%M')}"
        f" · {counts['total']} stories · {counts['high']} high / {counts['medium']} medium"
        f" / {counts['low']} low · analysis: {report.ai_provider}"
        + (f" ({report.ai_model})" if report.ai_model else "")
        + "</p><hr>"
    )
    body = markdown_to_html(report.ai_summary or "_No summary available._")
    errors = ""
    if report.errors:
        items = "".join(f"<li>{e}</li>" for e in report.errors[:8])
        errors = f"<hr><p class='meta'>Issues this run:</p><ul class='meta'>{items}</ul>"
    return f"<style>{_base_css()}</style>{header}{body}{errors}"
