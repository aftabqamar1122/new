"""End-to-end run: collect → filter/rank → summarize → export."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable

from . import sources as sources_mod
from .ai import ProviderError, get_provider
from .analysis import analyze
from .config import Config
from .export import write_reports
from .models import Report
from .summarize import fallback_summary, rerank, summarize

Logger = Callable[[str, str], None]
Progress = Callable[[int, str], None]


def _noop_progress(percent: int, message: str) -> None:  # pragma: no cover
    pass


def run(
    config: Config,
    log: Logger,
    progress: Progress | None = None,
    cancelled: Callable[[], bool] | None = None,
) -> Report:
    """Execute one full collection. Never raises for recoverable problems."""
    progress = progress or _noop_progress
    is_cancelled = cancelled or (lambda: False)

    report = Report(generated_at=datetime.now(timezone.utc))
    log("info", "=" * 52)
    log("info", "Starting collection run")

    # 1. Fetch ---------------------------------------------------------
    progress(5, "Fetching feeds…")
    enabled = config.enabled_sources()
    if not enabled:
        log("error", "No sources are enabled — check Settings → Sources")
        report.errors.append("No sources enabled.")
        report.ai_summary = fallback_summary([])
        return report

    articles, ok, failed, errors = sources_mod.collect(
        enabled,
        config.get("network", {}),
        int(config.get("collection.per_feed_limit", 40)),
        log,
    )
    report.feeds_ok, report.feeds_failed = ok, failed
    report.errors.extend(errors)
    report.raw_count = len(articles)

    if is_cancelled():
        log("warn", "Run cancelled after fetch")
        report.errors.append("Cancelled by user.")
        report.ai_summary = fallback_summary(report.articles)
        return report

    # 2. Filter, classify, rank ---------------------------------------
    progress(45, "Filtering and ranking…")
    report.articles = analyze(articles, config.get("collection", {}), log)

    if is_cancelled():
        log("warn", "Run cancelled after analysis")
        report.errors.append("Cancelled by user.")
        report.ai_summary = fallback_summary(report.articles)
        return report

    # 3. AI analysis ---------------------------------------------------
    progress(60, "Generating AI brief…")
    provider_name = config.provider_name()
    ai_enabled = bool(config.get("ai.enabled", True))
    provider = None
    if ai_enabled:
        try:
            provider = get_provider(
                provider_name, config.provider_config(provider_name), config.get("network", {})
            )
        except KeyError as exc:
            log("error", str(exc))
            report.errors.append(str(exc))

    if provider is None:
        reason = "AI disabled" if not ai_enabled else "no provider selected"
        log("info", f"Skipping AI analysis ({reason}) — using heuristic summary")
        report.ai_provider = "none"
        report.ai_summary = fallback_summary(report.articles)
    else:
        report.ai_provider = provider.label
        report.ai_model = provider.model
        if config.get("ai.rank_with_ai", False):
            progress(65, "AI re-ranking stories…")
            try:
                rerank(provider, report.articles, log)
            except ProviderError as exc:
                log("warn", f"AI ranking unavailable — {exc}")
                report.errors.append(f"AI ranking: {exc}")
        try:
            report.ai_summary = summarize(provider, report.articles, log)
        except ProviderError as exc:
            log("error", f"AI brief failed — {exc}")
            report.errors.append(f"AI brief: {exc}")
            report.ai_provider = f"{provider.label} (failed)"
            report.ai_summary = fallback_summary(report.articles)
        except Exception as exc:  # noqa: BLE001 - never lose a collected batch
            log("error", f"Unexpected AI failure — {type(exc).__name__}: {exc}")
            report.errors.append(f"AI brief: {type(exc).__name__}: {exc}")
            report.ai_provider = f"{provider.label} (failed)"
            report.ai_summary = fallback_summary(report.articles)

    # 4. Export --------------------------------------------------------
    if config.get("export.auto_export", True):
        progress(90, "Writing report files…")
        try:
            paths = write_reports(
                report, config.export_dir(), list(config.get("export.formats", []))
            )
            report.files = [str(p) for p in paths]
            for path in paths:
                log("success", f"Wrote {path}")
        except OSError as exc:
            log("error", f"Export failed — {exc}")
            report.errors.append(f"Export: {exc}")

    progress(100, "Done")
    counts = report.counts
    log(
        "success",
        f"Run complete — {counts['total']} stories "
        f"({counts['high']} high / {counts['medium']} medium / {counts['low']} low)",
    )
    return report
