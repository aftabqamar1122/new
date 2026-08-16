"""Settings dialog — everything the app reads at runtime is editable here."""

from __future__ import annotations

import copy
from typing import Any

from PySide6.QtCore import Qt, QThread, QTime, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTimeEdit,
    QVBoxLayout,
    QWidget,
)

from ..ai import PROVIDER_LABELS, ProviderError, available_providers, get_provider
from ..config import DEFAULT_CONFIG, ENV_KEYS, Config
from ..sources import DEFAULT_SOURCES
from . import theme

CATEGORY_CHOICES = ["mixed", "military", "financial"]


class _TestWorker(QThread):
    done = Signal(bool, str)

    def __init__(self, name: str, cfg: dict[str, Any], net: dict[str, Any], parent=None):
        super().__init__(parent)
        self._name, self._cfg, self._net = name, cfg, net

    def run(self) -> None:
        try:
            provider = get_provider(self._name, self._cfg, self._net)
            if provider is None:
                self.done.emit(True, "AI is disabled — nothing to test.")
                return
            usable, reason = provider.ready()
            if not usable:
                self.done.emit(False, reason)
                return
            reply = provider.complete(
                "You are a connectivity check. Reply with one short word.",
                "Reply with the single word: ready",
            )
            self.done.emit(True, f"{provider.label} responded: {reply.strip()[:120]}")
        except ProviderError as exc:
            self.done.emit(False, str(exc))
        except Exception as exc:  # noqa: BLE001
            self.done.emit(False, f"{type(exc).__name__}: {exc}")


class SettingsDialog(QDialog):
    def __init__(self, config: Config, parent=None):
        super().__init__(parent)
        self.setWindowTitle("NewsDesk Settings")
        self.setMinimumSize(760, 620)
        self.setWindowIcon(theme.app_icon())

        # Edit a copy; only commit to the live config on Save.
        self.working = copy.deepcopy(config.data)
        self._current_provider = self.working["ai"].get("provider", "anthropic")
        self._test_worker: _TestWorker | None = None

        tabs = QTabWidget()
        tabs.addTab(self._ai_tab(), "AI")
        tabs.addTab(self._schedule_tab(), "Schedule")
        tabs.addTab(self._collection_tab(), "Collection")
        tabs.addTab(self._sources_tab(), "Sources")
        tabs.addTab(self._network_tab(), "Network")
        tabs.addTab(self._output_tab(), "Output")

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Save).setObjectName("primary")
        buttons.accepted.connect(self._on_save)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(tabs)
        layout.addWidget(buttons)

    # ------------------------------------------------------------------
    # AI
    # ------------------------------------------------------------------

    def _ai_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)

        self.ai_enabled = QCheckBox("Use an AI provider for the daily brief")
        self.ai_enabled.setChecked(bool(self.working["ai"].get("enabled", True)))
        self.ai_rank = QCheckBox(
            "Also let the AI re-rank importance (one extra request per run)"
        )
        self.ai_rank.setChecked(bool(self.working["ai"].get("rank_with_ai", False)))

        self.provider_combo = QComboBox()
        for name in available_providers():
            self.provider_combo.addItem(PROVIDER_LABELS.get(name, name), name)
        index = self.provider_combo.findData(self._current_provider)
        self.provider_combo.setCurrentIndex(max(0, index))
        self.provider_combo.currentIndexChanged.connect(self._on_provider_changed)

        top = QFormLayout()
        top.addRow(self.ai_enabled)
        top.addRow(self.ai_rank)
        top.addRow("Provider", self.provider_combo)
        layout.addLayout(top)

        self.provider_box = QGroupBox("Provider settings")
        form = QFormLayout(self.provider_box)
        self.model_edit = QLineEdit()
        self.key_edit = QLineEdit()
        self.key_edit.setEchoMode(QLineEdit.Password)
        self.base_edit = QLineEdit()
        self.tokens_spin = QSpinBox()
        self.tokens_spin.setRange(256, 200_000)
        self.tokens_spin.setSingleStep(500)

        show_key = QCheckBox("Show")
        show_key.toggled.connect(
            lambda on: self.key_edit.setEchoMode(
                QLineEdit.Normal if on else QLineEdit.Password
            )
        )
        key_row = QHBoxLayout()
        key_row.addWidget(self.key_edit)
        key_row.addWidget(show_key)
        key_holder = QWidget()
        key_holder.setLayout(key_row)

        form.addRow("Model", self.model_edit)
        form.addRow("API key", key_holder)
        form.addRow("Base URL", self.base_edit)
        form.addRow("Max tokens", self.tokens_spin)

        self.key_hint = QLabel()
        self.key_hint.setWordWrap(True)
        self.key_hint.setStyleSheet(f"color: {theme.MUTED};")
        form.addRow(self.key_hint)

        test_row = QHBoxLayout()
        self.test_button = QPushButton("Test connection")
        self.test_button.clicked.connect(self._on_test)
        self.test_label = QLabel("")
        self.test_label.setWordWrap(True)
        test_row.addWidget(self.test_button)
        test_row.addWidget(self.test_label, 1)
        form.addRow(test_row)

        layout.addWidget(self.provider_box)
        layout.addStretch(1)
        self._load_provider_fields(self._current_provider)
        return page

    def _load_provider_fields(self, name: str) -> None:
        enabled = name != "none"
        self.provider_box.setEnabled(enabled)
        if not enabled:
            self.key_hint.setText(
                "No AI provider selected. Reports still collect, filter, tag regions "
                "and rank importance — the brief is generated from those heuristics."
            )
            return
        cfg = self.working["ai"]["providers"].get(name, {})
        self.model_edit.setText(cfg.get("model", ""))
        self.key_edit.setText(cfg.get("api_key", ""))
        self.base_edit.setText(cfg.get("base_url", ""))
        self.tokens_spin.setValue(int(cfg.get("max_tokens", 8000) or 8000))
        env = ENV_KEYS.get(name)
        default_model = (
            DEFAULT_CONFIG["ai"]["providers"].get(name, {}).get("model", "")
        )
        hint = f"Default model: {default_model}. "
        if env:
            hint += f"Leave the key blank to fall back to the {env} environment variable."
        else:
            hint += "No API key required for a local server."
        self.key_hint.setText(hint)
        self.test_label.setText("")

    def _store_provider_fields(self, name: str) -> None:
        if name == "none":
            return
        self.working["ai"]["providers"].setdefault(name, {})
        self.working["ai"]["providers"][name].update(
            {
                "model": self.model_edit.text().strip(),
                "api_key": self.key_edit.text().strip(),
                "base_url": self.base_edit.text().strip(),
                "max_tokens": int(self.tokens_spin.value()),
            }
        )

    def _on_provider_changed(self) -> None:
        self._store_provider_fields(self._current_provider)
        self._current_provider = self.provider_combo.currentData()
        self._load_provider_fields(self._current_provider)

    def _on_test(self) -> None:
        name = self.provider_combo.currentData()
        self._store_provider_fields(name)
        if name == "none":
            self.test_label.setText("AI is disabled.")
            return
        cfg = dict(self.working["ai"]["providers"].get(name, {}))
        if not cfg.get("api_key") and name in ENV_KEYS:
            import os

            cfg["api_key"] = os.environ.get(ENV_KEYS[name], "")
        self.test_button.setEnabled(False)
        self.test_label.setText("Testing…")
        self.test_label.setStyleSheet(f"color: {theme.MUTED};")
        self._test_worker = _TestWorker(name, cfg, self._network_values(), self)
        self._test_worker.done.connect(self._on_test_done)
        self._test_worker.start()

    def _on_test_done(self, ok: bool, message: str) -> None:
        self.test_button.setEnabled(True)
        self.test_label.setStyleSheet(
            f"color: {theme.SUCCESS if ok else theme.ERROR};"
        )
        self.test_label.setText(("OK — " if ok else "Failed — ") + message)

    # ------------------------------------------------------------------
    # Schedule
    # ------------------------------------------------------------------

    def _schedule_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        schedule = self.working["schedule"]

        self.sched_enabled = QCheckBox("Collect automatically at the times below")
        self.sched_enabled.setChecked(bool(schedule.get("enabled", True)))
        self.sched_on_start = QCheckBox("Also collect once when the app starts")
        self.sched_on_start.setChecked(bool(schedule.get("run_on_start", False)))
        layout.addWidget(self.sched_enabled)
        layout.addWidget(self.sched_on_start)

        box = QGroupBox("Daily run times (local time)")
        box_layout = QVBoxLayout(box)
        self.times_list = QListWidget()
        self.times_list.addItems(sorted(schedule.get("times", [])))
        box_layout.addWidget(self.times_list)

        row = QHBoxLayout()
        self.time_edit = QTimeEdit()
        self.time_edit.setDisplayFormat("HH:mm")
        self.time_edit.setTime(QTime(9, 0))
        add = QPushButton("Add time")
        add.clicked.connect(self._add_time)
        remove = QPushButton("Remove selected")
        remove.clicked.connect(self._remove_time)
        row.addWidget(self.time_edit)
        row.addWidget(add)
        row.addWidget(remove)
        row.addStretch(1)
        box_layout.addLayout(row)
        layout.addWidget(box)

        note = QLabel(
            "Times that have already passed today are skipped until tomorrow. "
            "Keep the app running (it can sit in the system tray) for scheduled "
            "runs to fire."
        )
        note.setWordWrap(True)
        note.setStyleSheet(f"color: {theme.MUTED};")
        layout.addWidget(note)
        layout.addStretch(1)
        return page

    def _add_time(self) -> None:
        value = self.time_edit.time().toString("HH:mm")
        existing = {
            self.times_list.item(i).text() for i in range(self.times_list.count())
        }
        if value in existing:
            return
        self.times_list.addItem(value)
        self.times_list.sortItems()

    def _remove_time(self) -> None:
        for item in self.times_list.selectedItems():
            self.times_list.takeItem(self.times_list.row(item))

    # ------------------------------------------------------------------
    # Collection
    # ------------------------------------------------------------------

    def _collection_tab(self) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        collection = self.working["collection"]

        self.age_spin = QSpinBox()
        self.age_spin.setRange(1, 168)
        self.age_spin.setSuffix(" hours")
        self.age_spin.setValue(int(collection.get("max_age_hours", 24)))

        self.max_articles_spin = QSpinBox()
        self.max_articles_spin.setRange(10, 1000)
        self.max_articles_spin.setValue(int(collection.get("max_articles", 120)))

        self.per_feed_spin = QSpinBox()
        self.per_feed_spin.setRange(5, 200)
        self.per_feed_spin.setValue(int(collection.get("per_feed_limit", 40)))

        self.min_title_spin = QSpinBox()
        self.min_title_spin.setRange(0, 100)
        self.min_title_spin.setValue(int(collection.get("min_title_length", 15)))

        self.keep_other = QCheckBox(
            "Keep stories that are neither military nor financial"
        )
        self.keep_other.setChecked(bool(collection.get("keep_other_category", False)))

        self.collapse_dupes = QCheckBox(
            "Merge the same story reported by several outlets into one entry"
        )
        self.collapse_dupes.setChecked(bool(collection.get("collapse_duplicates", True)))

        form.addRow("Discard stories older than", self.age_spin)
        form.addRow("Maximum stories per report", self.max_articles_spin)
        form.addRow("Maximum items read per feed", self.per_feed_spin)
        form.addRow("Minimum headline length", self.min_title_spin)
        form.addRow(self.keep_other)
        form.addRow(self.collapse_dupes)

        note = QLabel(
            "Stories are scored on impact language, source tier, recency and how "
            "many outlets carry the same story, then graded high / medium / low."
        )
        note.setWordWrap(True)
        note.setStyleSheet(f"color: {theme.MUTED};")
        form.addRow(note)
        return page

    # ------------------------------------------------------------------
    # Sources
    # ------------------------------------------------------------------

    def _sources_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)

        self.sources_table = QTableWidget(0, 5)
        self.sources_table.setHorizontalHeaderLabels(
            ["On", "Feed name", "Publisher", "Hint", "URL"]
        )
        self.sources_table.verticalHeader().setVisible(False)
        self.sources_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        header = self.sources_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.Interactive)
        header.setSectionResizeMode(2, QHeaderView.Interactive)
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.Stretch)
        self.sources_table.setColumnWidth(1, 180)
        self.sources_table.setColumnWidth(2, 130)
        layout.addWidget(self.sources_table)

        for source in self.working.get("sources", []):
            self._add_source_row(source)

        row = QHBoxLayout()
        add = QPushButton("Add feed")
        add.clicked.connect(lambda: self._add_source_row({"enabled": True}))
        remove = QPushButton("Remove selected")
        remove.clicked.connect(self._remove_source_rows)
        reset = QPushButton("Restore defaults")
        reset.clicked.connect(self._reset_sources)
        row.addWidget(add)
        row.addWidget(remove)
        row.addWidget(reset)
        row.addStretch(1)
        layout.addLayout(row)

        note = QLabel(
            "Reuters, Bloomberg and AP no longer publish open RSS, so they are "
            "followed through Google News feeds scoped to their own domains. "
            "'Hint' nudges classification; the text of each story decides the "
            "final category."
        )
        note.setWordWrap(True)
        note.setStyleSheet(f"color: {theme.MUTED};")
        layout.addWidget(note)
        return page

    def _add_source_row(self, source: dict[str, Any]) -> None:
        row = self.sources_table.rowCount()
        self.sources_table.insertRow(row)

        check = QTableWidgetItem()
        check.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled | Qt.ItemIsSelectable)
        check.setCheckState(
            Qt.Checked if source.get("enabled", True) else Qt.Unchecked
        )
        self.sources_table.setItem(row, 0, check)
        self.sources_table.setItem(row, 1, QTableWidgetItem(source.get("name", "")))
        self.sources_table.setItem(row, 2, QTableWidgetItem(source.get("source", "")))

        combo = QComboBox()
        combo.addItems(CATEGORY_CHOICES)
        hint = source.get("category", "mixed")
        combo.setCurrentIndex(
            CATEGORY_CHOICES.index(hint) if hint in CATEGORY_CHOICES else 0
        )
        self.sources_table.setCellWidget(row, 3, combo)
        self.sources_table.setItem(row, 4, QTableWidgetItem(source.get("url", "")))

    def _remove_source_rows(self) -> None:
        for index in sorted(
            {i.row() for i in self.sources_table.selectedIndexes()}, reverse=True
        ):
            self.sources_table.removeRow(index)

    def _reset_sources(self) -> None:
        confirm = QMessageBox.question(
            self,
            "Restore default feeds",
            "Replace the current feed list with the built-in defaults?",
        )
        if confirm != QMessageBox.Yes:
            return
        self.sources_table.setRowCount(0)
        for source in copy.deepcopy(DEFAULT_SOURCES):
            self._add_source_row(source)

    def _collect_sources(self) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for row in range(self.sources_table.rowCount()):
            url = (self.sources_table.item(row, 4).text() if self.sources_table.item(row, 4) else "").strip()
            name = (self.sources_table.item(row, 1).text() if self.sources_table.item(row, 1) else "").strip()
            if not url:
                continue
            combo = self.sources_table.cellWidget(row, 3)
            out.append(
                {
                    "enabled": self.sources_table.item(row, 0).checkState() == Qt.Checked,
                    "name": name or url,
                    "source": (
                        self.sources_table.item(row, 2).text().strip()
                        if self.sources_table.item(row, 2)
                        else ""
                    )
                    or name,
                    "category": combo.currentText() if combo else "mixed",
                    "url": url,
                }
            )
        return out

    # ------------------------------------------------------------------
    # Network
    # ------------------------------------------------------------------

    def _network_tab(self) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        net = self.working["network"]

        self.timeout_spin = QSpinBox()
        self.timeout_spin.setRange(5, 300)
        self.timeout_spin.setSuffix(" s")
        self.timeout_spin.setValue(int(net.get("timeout", 20)))

        self.retries_spin = QSpinBox()
        self.retries_spin.setRange(0, 5)
        self.retries_spin.setValue(int(net.get("retries", 2)))

        self.concurrency_spin = QSpinBox()
        self.concurrency_spin.setRange(1, 16)
        self.concurrency_spin.setValue(int(net.get("concurrency", 8)))

        self.verify_ssl = QCheckBox("Verify TLS certificates (recommended)")
        self.verify_ssl.setChecked(bool(net.get("verify_ssl", True)))

        self.proxy_edit = QLineEdit(net.get("proxy", ""))
        self.proxy_edit.setPlaceholderText("http://user:pass@proxy.example:8080")
        self.agent_edit = QLineEdit(net.get("user_agent", ""))

        form.addRow("Request timeout", self.timeout_spin)
        form.addRow("Retries per feed", self.retries_spin)
        form.addRow("Parallel feed fetches", self.concurrency_spin)
        form.addRow(self.verify_ssl)
        form.addRow("HTTP(S) proxy", self.proxy_edit)
        form.addRow("User agent", self.agent_edit)

        note = QLabel(
            "The proxy and timeout apply to feed downloads and to API calls. "
            "AI requests get six times the timeout, since analysis is slower "
            "than a feed fetch."
        )
        note.setWordWrap(True)
        note.setStyleSheet(f"color: {theme.MUTED};")
        form.addRow(note)
        return page

    def _network_values(self) -> dict[str, Any]:
        return {
            "timeout": int(self.timeout_spin.value()),
            "retries": int(self.retries_spin.value()),
            "concurrency": int(self.concurrency_spin.value()),
            "verify_ssl": bool(self.verify_ssl.isChecked()),
            "proxy": self.proxy_edit.text().strip(),
            "user_agent": self.agent_edit.text().strip(),
        }

    # ------------------------------------------------------------------
    # Output / interface
    # ------------------------------------------------------------------

    def _output_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        export = self.working["export"]
        ui = self.working["ui"]

        box = QGroupBox("Reports")
        form = QFormLayout(box)
        self.dir_edit = QLineEdit(export.get("directory", ""))
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._browse_dir)
        dir_row = QHBoxLayout()
        dir_row.addWidget(self.dir_edit)
        dir_row.addWidget(browse)
        dir_holder = QWidget()
        dir_holder.setLayout(dir_row)

        self.auto_export = QCheckBox("Write report files after every run")
        self.auto_export.setChecked(bool(export.get("auto_export", True)))
        formats = export.get("formats", [])
        self.fmt_md = QCheckBox("Markdown (.md)")
        self.fmt_md.setChecked("markdown" in formats)
        self.fmt_html = QCheckBox("HTML (.html)")
        self.fmt_html.setChecked("html" in formats)

        form.addRow("Output folder", dir_holder)
        form.addRow(self.auto_export)
        form.addRow("Formats", self.fmt_md)
        form.addRow("", self.fmt_html)
        layout.addWidget(box)

        ui_box = QGroupBox("Window & tray")
        ui_form = QVBoxLayout(ui_box)
        self.min_tray = QCheckBox("Closing the window keeps NewsDesk in the system tray")
        self.min_tray.setChecked(bool(ui.get("minimize_to_tray", True)))
        self.start_min = QCheckBox("Start minimised to the tray")
        self.start_min.setChecked(bool(ui.get("start_minimized", False)))
        self.notify = QCheckBox("Show a tray notification when a run finishes")
        self.notify.setChecked(bool(ui.get("notify_on_complete", True)))
        ui_form.addWidget(self.min_tray)
        ui_form.addWidget(self.start_min)
        ui_form.addWidget(self.notify)
        layout.addWidget(ui_box)
        layout.addStretch(1)
        return page

    def _browse_dir(self) -> None:
        chosen = QFileDialog.getExistingDirectory(
            self, "Choose report folder", self.dir_edit.text()
        )
        if chosen:
            self.dir_edit.setText(chosen)

    # ------------------------------------------------------------------

    def _on_save(self) -> None:
        formats = [
            fmt
            for fmt, checked in (
                ("markdown", self.fmt_md.isChecked()),
                ("html", self.fmt_html.isChecked()),
            )
            if checked
        ]
        if self.auto_export.isChecked() and not formats:
            QMessageBox.warning(
                self,
                "Choose a format",
                "Automatic export is on, so pick at least one output format.",
            )
            return
        self._store_provider_fields(self.provider_combo.currentData())
        self.working["ai"]["provider"] = self.provider_combo.currentData()
        self.working["ai"]["enabled"] = self.ai_enabled.isChecked()
        self.working["ai"]["rank_with_ai"] = self.ai_rank.isChecked()

        self.working["schedule"] = {
            "enabled": self.sched_enabled.isChecked(),
            "run_on_start": self.sched_on_start.isChecked(),
            "times": [
                self.times_list.item(i).text() for i in range(self.times_list.count())
            ],
        }
        self.working["collection"] = {
            "max_age_hours": int(self.age_spin.value()),
            "max_articles": int(self.max_articles_spin.value()),
            "per_feed_limit": int(self.per_feed_spin.value()),
            "min_title_length": int(self.min_title_spin.value()),
            "keep_other_category": self.keep_other.isChecked(),
            "collapse_duplicates": self.collapse_dupes.isChecked(),
        }
        self.working["network"] = self._network_values()
        self.working["sources"] = self._collect_sources()
        self.working["export"] = {
            "directory": self.dir_edit.text().strip(),
            "auto_export": self.auto_export.isChecked(),
            "formats": formats,
        }
        self.working["ui"] = {
            "minimize_to_tray": self.min_tray.isChecked(),
            "start_minimized": self.start_min.isChecked(),
            "notify_on_complete": self.notify.isChecked(),
        }
        self.accept()

    def result_data(self) -> dict[str, Any]:
        return self.working
