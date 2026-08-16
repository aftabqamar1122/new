"""Report rendering: Markdown, standalone dark-themed HTML, and a tiny
Markdown→HTML converter used for the in-app summary pane."""

from __future__ import annotations

import html
import re
from pathlib import Path

from .models import (
    CATEGORY_FINANCIAL,
    CATEGORY_MILITARY,
    IMPORTANCE_HIGH,
    IMPORTANCE_LOW,
    IMPORTANCE_MEDIUM,
    Article,
    Report,
)

IMPORTANCE_BADGE = {
    IMPORTANCE_HIGH: "🔴 HIGH",
    IMPORTANCE_MEDIUM: "🟠 MEDIUM",
    IMPORTANCE_LOW: "⚪ LOW",
}


# --------------------------------------------------------------------------
# Markdown
# --------------------------------------------------------------------------

def render_markdown(report: Report) -> str:
    counts = report.counts
    lines: list[str] = [
        f"# {report.title()}",
        "",
        f"*Generated {report.generated_at.astimezone().strftime('%Y-%m-%d %H:%M %Z')} "
        f"by NewsDesk — analysis: {report.ai_provider}"
        + (f" / {report.ai_model}" if report.ai_model else "")
        + "*",
        "",
        f"**{counts['total']} stories** · {counts[IMPORTANCE_HIGH]} high · "
        f"{counts[IMPORTANCE_MEDIUM]} medium · {counts[IMPORTANCE_LOW]} low · "
        f"{counts[CATEGORY_MILITARY]} military · {counts[CATEGORY_FINANCIAL]} financial · "
        f"{report.feeds_ok} feeds OK / {report.feeds_failed} failed",
        "",
        "---",
        "",
        report.ai_summary.strip() or "_No summary available._",
        "",
        "---",
        "",
    ]

    for label, category in (
        ("Military & security stories", CATEGORY_MILITARY),
        ("Financial & economic stories", CATEGORY_FINANCIAL),
    ):
        articles = report.by_category(category)
        lines.append(f"## {label} ({len(articles)})")
        lines.append("")
        if not articles:
            lines.extend(["_No stories in this category._", ""])
            continue
        for importance in (IMPORTANCE_HIGH, IMPORTANCE_MEDIUM, IMPORTANCE_LOW):
            bucket = [a for a in articles if a.importance == importance]
            if not bucket:
                continue
            lines.append(f"### {IMPORTANCE_BADGE[importance]} ({len(bucket)})")
            lines.append("")
            lines.extend(_markdown_article(a) for a in bucket)
            lines.append("")

    if report.errors:
        lines.extend(["## Collection issues", ""])
        lines.extend(f"- {error}" for error in report.errors)
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def _markdown_article(article: Article) -> str:
    title = f"[{article.title}]({article.link})" if article.link else article.title
    meta = f"{article.source} · {article.region} · {article.published_label()}"
    if article.corroborating_sources:
        meta += f" · also: {', '.join(article.corroborating_sources[:3])}"
    body = f"- **{title}**  \n  {meta}"
    if article.summary:
        body += f"  \n  {article.summary}"
    return body


# --------------------------------------------------------------------------
# HTML
# --------------------------------------------------------------------------

_HTML_TEMPLATE = """<!doctype html>
<html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
:root {{
  --bg:#12151c; --panel:#1a1f29; --panel-2:#212836; --line:#2c3446;
  --text:#e6eaf2; --muted:#94a0b8; --accent:#5b9dff;
  --high:#ff5f56; --medium:#ffa23a; --low:#7e8aa2;
}}
* {{ box-sizing:border-box; }}
body {{ margin:0; padding:32px 20px; background:var(--bg); color:var(--text);
  font:15px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif; }}
.wrap {{ max-width:900px; margin:0 auto; }}
h1 {{ font-size:26px; margin:0 0 6px; letter-spacing:-.01em; }}
h2 {{ font-size:19px; margin:34px 0 12px; padding-bottom:8px; border-bottom:1px solid var(--line); }}
h3 {{ font-size:15px; margin:22px 0 10px; color:var(--muted); text-transform:uppercase;
  letter-spacing:.08em; }}
a {{ color:var(--accent); text-decoration:none; }}
a:hover {{ text-decoration:underline; }}
.sub {{ color:var(--muted); font-size:13px; margin-bottom:18px; }}
.stats {{ display:flex; flex-wrap:wrap; gap:8px; margin-bottom:26px; }}
.stat {{ background:var(--panel); border:1px solid var(--line); border-radius:8px;
  padding:8px 12px; font-size:13px; color:var(--muted); }}
.stat b {{ color:var(--text); font-size:15px; }}
.brief {{ background:var(--panel); border:1px solid var(--line); border-left:3px solid var(--accent);
  border-radius:10px; padding:4px 22px 18px; margin-bottom:14px; }}
.brief h2 {{ font-size:16px; border:0; margin:20px 0 8px; }}
.card {{ background:var(--panel); border:1px solid var(--line); border-radius:10px;
  padding:14px 16px; margin-bottom:10px; }}
.card.high {{ border-left:3px solid var(--high); }}
.card.medium {{ border-left:3px solid var(--medium); }}
.card.low {{ border-left:3px solid var(--low); }}
.card .headline {{ font-weight:600; font-size:15px; margin-bottom:6px; }}
.meta {{ color:var(--muted); font-size:12.5px; display:flex; flex-wrap:wrap; gap:10px; }}
.chip {{ background:var(--panel-2); border-radius:999px; padding:2px 9px; font-size:11.5px;
  letter-spacing:.03em; }}
.chip.high {{ color:var(--high); }} .chip.medium {{ color:var(--medium); }}
.chip.low {{ color:var(--low); }}
.desc {{ color:#c3cbdb; font-size:13.5px; margin-top:8px; }}
.errors {{ color:var(--muted); font-size:13px; }}
footer {{ margin-top:40px; padding-top:14px; border-top:1px solid var(--line);
  color:var(--muted); font-size:12px; }}
@media print {{ body {{ background:#fff; color:#111; }} .card,.brief {{ background:#fff; }} }}
</style></head>
<body><div class="wrap">
<h1>{title}</h1>
<div class="sub">Generated {generated} by NewsDesk · analysis: {provider}</div>
<div class="stats">{stats}</div>
<div class="brief">{brief}</div>
{sections}
{errors}
<footer>NewsDesk · {feeds_ok} feeds collected, {feeds_failed} failed · headlines link to the
original publishers.</footer>
</div></body></html>
"""


def render_html(report: Report) -> str:
    counts = report.counts
    stats = "".join(
        f'<div class="stat"><b>{value}</b> {label}</div>'
        for label, value in (
            ("stories", counts["total"]),
            ("high", counts[IMPORTANCE_HIGH]),
            ("medium", counts[IMPORTANCE_MEDIUM]),
            ("low", counts[IMPORTANCE_LOW]),
            ("military", counts[CATEGORY_MILITARY]),
            ("financial", counts[CATEGORY_FINANCIAL]),
        )
    )

    sections: list[str] = []
    for label, category in (
        ("Military &amp; security", CATEGORY_MILITARY),
        ("Financial &amp; economic", CATEGORY_FINANCIAL),
    ):
        articles = report.by_category(category)
        sections.append(f"<h2>{label} ({len(articles)})</h2>")
        if not articles:
            sections.append('<p class="errors">No stories in this category.</p>')
            continue
        for importance in (IMPORTANCE_HIGH, IMPORTANCE_MEDIUM, IMPORTANCE_LOW):
            bucket = [a for a in articles if a.importance == importance]
            if not bucket:
                continue
            sections.append(f"<h3>{importance} importance ({len(bucket)})</h3>")
            sections.extend(_html_card(a) for a in bucket)

    errors_html = ""
    if report.errors:
        items = "".join(f"<li>{html.escape(e)}</li>" for e in report.errors)
        errors_html = f"<h2>Collection issues</h2><ul class='errors'>{items}</ul>"

    provider = html.escape(report.ai_provider or "none")
    if report.ai_model:
        provider += f" / {html.escape(report.ai_model)}"

    return _HTML_TEMPLATE.format(
        title=html.escape(report.title()),
        generated=html.escape(
            report.generated_at.astimezone().strftime("%Y-%m-%d %H:%M %Z")
        ),
        provider=provider,
        stats=stats,
        brief=markdown_to_html(report.ai_summary or "_No summary available._"),
        sections="\n".join(sections),
        errors=errors_html,
        feeds_ok=report.feeds_ok,
        feeds_failed=report.feeds_failed,
    )


def _html_card(article: Article) -> str:
    title = html.escape(article.title)
    headline = (
        f'<a href="{html.escape(article.link, quote=True)}" target="_blank" '
        f'rel="noopener">{title}</a>'
        if article.link
        else title
    )
    chips = [
        f'<span class="chip {article.importance}">{article.importance.upper()}</span>',
        f'<span class="chip">{html.escape(article.region)}</span>',
    ]
    if article.corroborating_sources:
        chips.append(
            f'<span class="chip">+{len(set(article.corroborating_sources))} outlets</span>'
        )
    meta = (
        f'<div class="meta">{"".join(chips)}'
        f"<span>{html.escape(article.source)}</span>"
        f"<span>{html.escape(article.published_label())}</span></div>"
    )
    desc = (
        f'<div class="desc">{html.escape(article.summary)}</div>' if article.summary else ""
    )
    return (
        f'<div class="card {article.importance}">'
        f'<div class="headline">{headline}</div>{meta}{desc}</div>'
    )


# --------------------------------------------------------------------------
# Minimal Markdown → HTML (headings, bullets, bold/italic, links, code)
# --------------------------------------------------------------------------

_LINK_RE = re.compile(r"\[([^\]]+)\]\((https?://[^\s)]+)\)")
_BOLD_RE = re.compile(r"\*\*([^*]+)\*\*")
_ITALIC_RE = re.compile(r"(?<!\*)\*([^*\n]+)\*(?!\*)")
_UNDERSCORE_RE = re.compile(r"(?<!\w)_([^_\n]+)_(?!\w)")
_CODE_RE = re.compile(r"`([^`]+)`")


def _inline(text: str) -> str:
    out = html.escape(text)
    out = _CODE_RE.sub(r"<code>\1</code>", out)
    out = _LINK_RE.sub(r'<a href="\2" target="_blank" rel="noopener">\1</a>', out)
    out = _BOLD_RE.sub(r"<strong>\1</strong>", out)
    out = _ITALIC_RE.sub(r"<em>\1</em>", out)
    out = _UNDERSCORE_RE.sub(r"<em>\1</em>", out)
    return out


def markdown_to_html(text: str) -> str:
    """Small, dependency-free renderer good enough for model-written briefs."""
    html_lines: list[str] = []
    in_list = False

    def close_list() -> None:
        nonlocal in_list
        if in_list:
            html_lines.append("</ul>")
            in_list = False

    for raw_line in (text or "").splitlines():
        line = raw_line.rstrip()
        stripped = line.strip()

        if not stripped:
            close_list()
            continue
        if stripped.startswith("---"):
            close_list()
            html_lines.append("<hr>")
            continue

        heading = re.match(r"^(#{1,4})\s+(.*)$", stripped)
        if heading:
            close_list()
            level = min(len(heading.group(1)) + 1, 5)
            html_lines.append(f"<h{level}>{_inline(heading.group(2))}</h{level}>")
            continue

        bullet = re.match(r"^[-*+]\s+(.*)$", stripped) or re.match(
            r"^\d+[.)]\s+(.*)$", stripped
        )
        if bullet:
            if not in_list:
                html_lines.append("<ul>")
                in_list = True
            html_lines.append(f"<li>{_inline(bullet.group(1))}</li>")
            continue

        close_list()
        html_lines.append(f"<p>{_inline(stripped)}</p>")

    close_list()
    return "\n".join(html_lines)


# --------------------------------------------------------------------------
# Writing to disk
# --------------------------------------------------------------------------

def write_reports(report: Report, directory: Path, formats: list[str]) -> list[Path]:
    """Write the requested formats and return the paths created."""
    directory.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    stem = f"newsdesk_{report.slug()}"

    if "markdown" in formats:
        path = directory / f"{stem}.md"
        path.write_text(render_markdown(report), encoding="utf-8")
        written.append(path)
    if "html" in formats:
        path = directory / f"{stem}.html"
        path.write_text(render_html(report), encoding="utf-8")
        written.append(path)
    return written
