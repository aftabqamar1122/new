"""Blueprint -> .pptx  (master layouts, assertion titles, speaker notes on every slide)."""

from __future__ import annotations

import re
from datetime import date, datetime
from pathlib import Path

from pptx import Presentation
from pptx.chart.data import CategoryChartData
from pptx.dml.color import RGBColor
from pptx.enum.chart import XL_CHART_TYPE, XL_LEGEND_POSITION
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.util import Emu, Inches, Pt

from .model import Blueprint, Section, Table
from .parse import column_kind
from .theme import Theme, get_theme, rgb

SLIDE_W, SLIDE_H = Inches(13.333), Inches(7.5)   # 16:9
MAX_BULLETS = 6
MAX_TABLE_ROWS = 12

LAYOUT_TITLE, LAYOUT_CONTENT, LAYOUT_SECTION, LAYOUT_TITLE_ONLY, LAYOUT_BLANK = 0, 1, 2, 5, 6


def _color(hex_str: str) -> RGBColor:
    return RGBColor(*rgb(hex_str))


def _fmt(value, kind: str) -> str:
    if value is None:
        return ""
    if isinstance(value, (date, datetime)):
        return value.strftime("%d-%b-%Y")
    if isinstance(value, (int, float)):
        if kind == "percent":
            return f"{value * 100:,.1f}%"
        if isinstance(value, int) or float(value).is_integer():
            return f"{int(value):,}"
        return f"{value:,.2f}"
    return str(value)


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", text.strip()) if len(s.strip()) > 2]


def _shorten(text: str, limit: int = 120) -> str:
    text = text.strip().rstrip(".")
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0]
    return cut + "…"


class Deck:
    def __init__(self, bp: Blueprint, theme: Theme):
        self.bp = bp
        self.theme = theme
        self.prs = Presentation()
        self.prs.slide_width, self.prs.slide_height = SLIDE_W, SLIDE_H

    # ---- chrome ---------------------------------------------------------
    def _accent_bar(self, slide) -> None:
        from pptx.enum.shapes import MSO_SHAPE
        bar = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(0.6), Inches(1.02),
                                     Inches(1.1), Pt(3.5))
        bar.fill.solid()
        bar.fill.fore_color.rgb = _color(self.theme.accent)
        bar.line.fill.background()
        bar.shadow.inherit = False

    def _footer(self, slide, index: int) -> None:
        box = slide.shapes.add_textbox(Inches(0.6), Inches(6.95), Inches(12.1), Inches(0.32))
        tf = box.text_frame
        tf.word_wrap = False
        p = tf.paragraphs[0]
        run = p.add_run()
        run.text = f"{self.bp.title}  ·  {self.bp.date}"
        run.font.size = Pt(9)
        run.font.color.rgb = _color(self.theme.muted)
        run.font.name = self.theme.body_font

        num = slide.shapes.add_textbox(Inches(12.2), Inches(6.95), Inches(0.55), Inches(0.32))
        np_ = num.text_frame.paragraphs[0]
        np_.alignment = PP_ALIGN.RIGHT
        r = np_.add_run()
        r.text = str(index)
        r.font.size = Pt(9)
        r.font.bold = True
        r.font.color.rgb = _color(self.theme.accent)
        r.font.name = self.theme.body_font

    def _notes(self, slide, text: str) -> None:
        slide.notes_slide.notes_text_frame.text = text.strip() or "—"

    def _style_title(self, shape, size: int = 28) -> None:
        tf = shape.text_frame
        tf.word_wrap = True
        for p in tf.paragraphs:
            p.alignment = PP_ALIGN.LEFT
            for run in p.runs:
                run.font.size = Pt(size)
                run.font.bold = True
                run.font.color.rgb = _color(self.theme.ink)
                run.font.name = self.theme.heading_font

    # ---- slides ---------------------------------------------------------
    def title_slide(self) -> None:
        slide = self.prs.slides.add_slide(self.prs.slide_layouts[LAYOUT_TITLE])
        slide.shapes.title.text = self.bp.title
        self._style_title(slide.shapes.title, 40)
        slide.shapes.title.left, slide.shapes.title.top = Inches(0.9), Inches(2.3)
        slide.shapes.title.width = Inches(11.5)

        sub = slide.placeholders[1]
        sub.left, sub.top, sub.width = Inches(0.95), Inches(3.7), Inches(11.5)
        parts = [self.bp.subtitle or "", self.bp.author, self.bp.date]
        sub.text_frame.text = "  ·  ".join([p for p in parts if p])
        for p in sub.text_frame.paragraphs:
            p.alignment = PP_ALIGN.LEFT
            for run in p.runs:
                run.font.size = Pt(15)
                run.font.color.rgb = _color(self.theme.muted)
                run.font.name = self.theme.body_font

        from pptx.enum.shapes import MSO_SHAPE
        bar = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(0.95), Inches(2.0),
                                     Inches(2.2), Pt(5))
        bar.fill.solid()
        bar.fill.fore_color.rgb = _color(self.theme.accent)
        bar.line.fill.background()
        bar.shadow.inherit = False
        self._notes(slide, f"Opening slide. {self.bp.title}. "
                           f"{'Prepared by ' + self.bp.author + '. ' if self.bp.author else ''}"
                           f"Set up the purpose in one sentence before moving on.")

    def section_slide(self, title: str, index: int, note: str = "") -> None:
        slide = self.prs.slides.add_slide(self.prs.slide_layouts[LAYOUT_SECTION])
        slide.shapes.title.text = title
        self._style_title(slide.shapes.title, 30)
        for ph in slide.placeholders:
            if ph.placeholder_format.idx != 0:
                ph.text_frame.text = ""
        self._footer(slide, index)
        self._notes(slide, note or f"Section divider: {title}.")

    def bullet_slide(self, title: str, bullets: list[str], index: int,
                     note: str = "", eyebrow: str = "") -> None:
        slide = self.prs.slides.add_slide(self.prs.slide_layouts[LAYOUT_CONTENT])
        slide.shapes.title.text = title
        slide.shapes.title.left, slide.shapes.title.top = Inches(0.6), Inches(0.42)
        slide.shapes.title.width, slide.shapes.title.height = Inches(12.1), Inches(0.85)
        self._style_title(slide.shapes.title, 26)
        self._accent_bar(slide)

        body = slide.placeholders[1]
        body.left, body.top = Inches(0.6), Inches(1.45)
        body.width, body.height = Inches(12.1), Inches(5.2)
        tf = body.text_frame
        tf.word_wrap = True
        tf.clear()
        size = 20 if len(bullets) <= 4 else (18 if len(bullets) <= 6 else 16)
        for i, b in enumerate(bullets):
            p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
            run = p.add_run()
            run.text = _shorten(b, 150)
            run.font.size = Pt(size)
            run.font.color.rgb = _color(self.theme.body)
            run.font.name = self.theme.body_font
            p.space_after = Pt(12)
            p.level = 0
        if eyebrow:
            box = slide.shapes.add_textbox(Inches(0.62), Inches(0.12), Inches(6), Inches(0.3))
            r = box.text_frame.paragraphs[0].add_run()
            r.text = eyebrow.upper()
            r.font.size = Pt(9)
            r.font.bold = True
            r.font.color.rgb = _color(self.theme.accent)
            r.font.name = self.theme.body_font
        self._footer(slide, index)
        self._notes(slide, note or "Talk to each point; the detail sits in the source data.")

    def table_slide(self, tbl: Table, index: int, title: str = "") -> None:
        slide = self.prs.slides.add_slide(self.prs.slide_layouts[LAYOUT_TITLE_ONLY])
        slide.shapes.title.text = title or tbl.name or "Data"
        slide.shapes.title.left, slide.shapes.title.top = Inches(0.6), Inches(0.42)
        slide.shapes.title.width, slide.shapes.title.height = Inches(12.1), Inches(0.85)
        self._style_title(slide.shapes.title, 26)
        self._accent_bar(slide)

        kinds = [column_kind([r[i] if i < len(r) else None for r in tbl.rows],
                             [str(r[i]) if i < len(r) and r[i] is not None else "" for r in tbl.rows])
                 for i in range(tbl.n_cols)]
        shown = tbl.rows[:MAX_TABLE_ROWS]
        rows, cols = len(shown) + 1, tbl.n_cols
        height = Inches(min(0.42 * rows + 0.3, 5.0))
        shape = slide.shapes.add_table(rows, cols, Inches(0.6), Inches(1.5),
                                       Inches(12.1), height)
        table = shape.table

        for i, h in enumerate(tbl.headers):
            cell = table.cell(0, i)
            cell.text = str(h)
            cell.fill.solid()
            cell.fill.fore_color.rgb = _color(self.theme.accent)
            cell.vertical_anchor = MSO_ANCHOR.MIDDLE
            for p in cell.text_frame.paragraphs:
                p.alignment = PP_ALIGN.RIGHT if kinds[i] in ("number", "currency", "percent") else PP_ALIGN.LEFT
                for run in p.runs:
                    run.font.size = Pt(12)
                    run.font.bold = True
                    run.font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)
                    run.font.name = self.theme.body_font

        for r, row in enumerate(shown, start=1):
            for i in range(cols):
                cell = table.cell(r, i)
                cell.text = _fmt(row[i] if i < len(row) else None, kinds[i])
                cell.fill.solid()
                cell.fill.fore_color.rgb = _color(self.theme.paper if r % 2 else self.theme.surface)
                cell.vertical_anchor = MSO_ANCHOR.MIDDLE
                for p in cell.text_frame.paragraphs:
                    p.alignment = PP_ALIGN.RIGHT if kinds[i] in ("number", "currency", "percent") else PP_ALIGN.LEFT
                    for run in p.runs:
                        run.font.size = Pt(11.5)
                        run.font.color.rgb = _color(self.theme.body)
                        run.font.name = self.theme.body_font

        if tbl.n_rows > MAX_TABLE_ROWS:
            box = slide.shapes.add_textbox(Inches(0.6), Inches(1.5) + height + Inches(0.1),
                                           Inches(8), Inches(0.3))
            r = box.text_frame.paragraphs[0].add_run()
            r.text = f"Showing {MAX_TABLE_ROWS} of {tbl.n_rows} rows — full data in the workbook."
            r.font.size = Pt(10)
            r.font.italic = True
            r.font.color.rgb = _color(self.theme.muted)
            r.font.name = self.theme.body_font

        self._footer(slide, index)
        self._notes(slide, f"{tbl.name}: {tbl.n_rows} rows, {tbl.n_cols} columns. "
                           f"Columns are {', '.join(tbl.headers)}.")

    def chart_slide(self, tbl: Table, index: int) -> bool:
        kinds = [column_kind([r[i] if i < len(r) else None for r in tbl.rows],
                             [str(r[i]) if i < len(r) and r[i] is not None else "" for r in tbl.rows])
                 for i in range(tbl.n_cols)]
        try:
            key = next(i for i, k in enumerate(kinds) if k == "text")
        except StopIteration:
            return False
        nums = [i for i, k in enumerate(kinds) if k in ("number", "currency", "percent")]
        if not nums:
            return False

        agg: dict[str, list[float]] = {}
        for row in tbl.rows:
            k = str(row[key]) if key < len(row) and row[key] is not None else "—"
            vals = agg.setdefault(k, [0.0] * len(nums))
            for j, i in enumerate(nums):
                v = row[i] if i < len(row) else None
                if isinstance(v, (int, float)):
                    vals[j] += float(v)
        if len(agg) < 2 or len(agg) > 12:
            return False

        slide = self.prs.slides.add_slide(self.prs.slide_layouts[LAYOUT_TITLE_ONLY])
        top_key = max(agg, key=lambda k: agg[k][0])
        total = sum(v[0] for v in agg.values()) or 1.0
        share = agg[top_key][0] / total
        slide.shapes.title.text = (f"{top_key} accounts for {share:.0%} of "
                                   f"{tbl.headers[nums[0]].lower()}")
        slide.shapes.title.left, slide.shapes.title.top = Inches(0.6), Inches(0.42)
        slide.shapes.title.width, slide.shapes.title.height = Inches(12.1), Inches(0.85)
        self._style_title(slide.shapes.title, 26)
        self._accent_bar(slide)

        data = CategoryChartData()
        data.categories = list(agg.keys())
        for j, i in enumerate(nums[:3]):
            data.add_series(tbl.headers[i], [agg[k][j] for k in agg])

        gf = slide.shapes.add_chart(XL_CHART_TYPE.COLUMN_CLUSTERED, Inches(0.7), Inches(1.5),
                                    Inches(11.9), Inches(4.9), data)
        chart = gf.chart
        chart.has_title = False
        chart.font.size = Pt(12)
        chart.font.color.rgb = _color(self.theme.body)
        if len(nums[:3]) > 1:
            chart.has_legend = True
            chart.legend.position = XL_LEGEND_POSITION.BOTTOM
            chart.legend.include_in_layout = False
        else:
            chart.has_legend = False
        for s_i, series in enumerate(chart.plots[0].series):
            series.format.fill.solid()
            series.format.fill.fore_color.rgb = _color(self.theme.series[s_i % len(self.theme.series)])
        plot = chart.plots[0]
        plot.gap_width = 60
        if len(nums[:3]) == 1:
            plot.has_data_labels = True
            plot.data_labels.font.size = Pt(11)
            plot.data_labels.font.color.rgb = _color(self.theme.muted)

        self._footer(slide, index)
        self._notes(slide, f"{tbl.headers[nums[0]]} by {tbl.headers[key]}. "
                           f"{top_key} is the largest at {agg[top_key][0]:,.0f} "
                           f"({share:.0%} of {total:,.0f}). Source: {self.bp.source}.")
        return True


def _section_bullets(sec: Section) -> list[str]:
    bullets = list(sec.bullets)
    for para in sec.paragraphs:
        bullets.extend(_sentences(para))
    return [b for b in bullets if b][:12]


def build(bp: Blueprint, out_path: str | Path, theme_name: str = "slate",
          max_slides: int = 40) -> Path:
    """Render the blueprint as a deck and return the written path."""
    theme = get_theme(theme_name)
    deck = Deck(bp, theme)
    deck.title_slide()
    n = 1

    if bp.summary:
        n += 1
        deck.bullet_slide("Executive summary", bp.summary[:6], n,
                          eyebrow="the whole story on one slide",
                          note="Deliver the entire argument here. Everything after this slide is evidence.")

    from .parse import ACTION_WORDS
    content_sections = [
        s for s in bp.sections
        if not (bp.summary and "summary" in s.heading.lower())
        and not (bp.next_steps and any(w in s.heading.lower() for w in ACTION_WORDS))
    ]
    if len(content_sections) >= 5:
        n += 1
        deck.bullet_slide("Agenda", [s.heading for s in content_sections[:8]], n,
                          note="Walk the agenda in ten seconds; do not read every line.")

    for sec in content_sections:
        bullets = _section_bullets(sec)
        chunks = [bullets[i:i + MAX_BULLETS] for i in range(0, len(bullets), MAX_BULLETS)] or [[]]
        for c_i, chunk in enumerate(chunks):
            if not chunk:
                continue
            if n >= max_slides:
                break
            n += 1
            title = sec.heading if c_i == 0 else f"{sec.heading} (cont.)"
            deck.bullet_slide(title, chunk, n, note=sec.notes)
        for tbl in sec.tables:
            if n >= max_slides:
                break
            n += 1
            charted = deck.chart_slide(tbl, n)
            if not charted:
                deck.table_slide(tbl, n)
            elif tbl.n_rows <= MAX_TABLE_ROWS and n < max_slides:
                n += 1
                deck.table_slide(tbl, n, title=f"Supporting data — {tbl.name}")

    for tbl in bp.tables:
        if n >= max_slides:
            break
        n += 1
        charted = deck.chart_slide(tbl, n)
        if not charted:
            deck.table_slide(tbl, n)
        elif tbl.n_rows <= MAX_TABLE_ROWS and n < max_slides:
            n += 1
            deck.table_slide(tbl, n, title=f"Supporting data — {tbl.name}")

    if bp.next_steps:
        n += 1
        deck.bullet_slide("Next steps", bp.next_steps[:6], n,
                          eyebrow="owner and date for each",
                          note="Close with commitments. Name an owner and a date for every line.")

    deck.section_slide("Thank you", n + 1,
                       note="Stop here and take questions. Backup detail is in the workbook.")

    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    deck.prs.save(out)
    return out
