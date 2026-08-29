"""Blueprint -> .docx  (styles-first, real headings, live TOC field)."""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

from docx import Document
from docx.enum.section import WD_SECTION
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor

from .model import Blueprint, Table
from .parse import column_kind
from .theme import Theme, get_theme, rgb


# ---------- low-level xml helpers ----------------------------------------
def _shade(cell, hex_fill: str) -> None:
    tc_pr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), hex_fill)
    tc_pr.append(shd)


def _cell_border(cell, edge: str, hex_color: str, sz: int = 6) -> None:
    tc_pr = cell._tc.get_or_add_tcPr()
    borders = tc_pr.find(qn("w:tcBorders"))
    if borders is None:
        borders = OxmlElement("w:tcBorders")
        tc_pr.append(borders)
    el = OxmlElement(f"w:{edge}")
    el.set(qn("w:val"), "single")
    el.set(qn("w:sz"), str(sz))
    el.set(qn("w:color"), hex_color)
    borders.append(el)


def _repeat_header(row) -> None:
    tr_pr = row._tr.get_or_add_trPr()
    el = OxmlElement("w:tblHeader")
    el.set(qn("w:val"), "true")
    tr_pr.append(el)


def _field(paragraph, instruction: str, placeholder: str = "") -> None:
    """Insert a real Word field so it updates with F9 / on open."""
    run = paragraph.add_run()
    begin = OxmlElement("w:fldChar")
    begin.set(qn("w:fldCharType"), "begin")
    instr = OxmlElement("w:instrText")
    instr.set(qn("xml:space"), "preserve")
    instr.text = f" {instruction} "
    sep = OxmlElement("w:fldChar")
    sep.set(qn("w:fldCharType"), "separate")
    txt = OxmlElement("w:t")
    txt.text = placeholder
    end = OxmlElement("w:fldChar")
    end.set(qn("w:fldCharType"), "end")
    for el in (begin, instr, sep, txt, end):
        run._r.append(el)


def _update_fields_on_open(doc: Document) -> None:
    settings = doc.settings.element
    el = OxmlElement("w:updateFields")
    el.set(qn("w:val"), "true")
    settings.append(el)


# ---------- formatting ----------------------------------------------------
def fmt_value(value, kind: str) -> str:
    if value is None:
        return ""
    if isinstance(value, (date, datetime)):
        return value.strftime("%d-%b-%Y")
    if isinstance(value, (int, float)):
        if kind == "percent":
            return f"{value * 100:,.1f}%"
        if kind == "currency":
            return f"{value:,.2f}"
        if isinstance(value, int) or float(value).is_integer():
            return f"{int(value):,}"
        return f"{value:,.2f}"
    return str(value)


def _setup_styles(doc: Document, theme: Theme) -> None:
    styles = doc.styles

    normal = styles["Normal"]
    normal.font.name = theme.body_font
    normal.font.size = Pt(10.5)
    normal.font.color.rgb = RGBColor(*rgb(theme.body))
    normal.paragraph_format.space_after = Pt(8)
    normal.paragraph_format.line_spacing = 1.15

    for name, size, color, before, after, bold in (
        ("Title", 30, theme.ink, 0, 6, True),
        ("Heading 1", 17, theme.accent, 18, 6, True),
        ("Heading 2", 13.5, theme.ink, 14, 4, True),
        ("Heading 3", 11.5, theme.body, 10, 3, True),
    ):
        st = styles[name]
        st.font.name = theme.heading_font if name != "Heading 3" else theme.body_font
        st.font.size = Pt(size)
        st.font.bold = bold
        st.font.color.rgb = RGBColor(*rgb(color))
        st.paragraph_format.space_before = Pt(before)
        st.paragraph_format.space_after = Pt(after)
        st.paragraph_format.keep_with_next = True

    cap = styles["Caption"]
    cap.font.name = theme.body_font
    cap.font.size = Pt(8.5)
    cap.font.italic = False
    cap.font.color.rgb = RGBColor(*rgb(theme.muted))

    quote = styles["Intense Quote"] if "Intense Quote" in [s.name for s in styles] else None
    if quote is not None:
        quote.font.color.rgb = RGBColor(*rgb(theme.accent))


def _page_setup(doc: Document) -> None:
    for section in doc.sections:
        section.page_width = Inches(8.27)    # A4
        section.page_height = Inches(11.69)
        section.top_margin = Inches(1.0)
        section.bottom_margin = Inches(0.9)
        section.left_margin = Inches(1.0)
        section.right_margin = Inches(1.0)


def _footer(doc: Document, bp: Blueprint, theme: Theme) -> None:
    for section in doc.sections:
        footer = section.footer
        p = footer.paragraphs[0] if footer.paragraphs else footer.add_paragraph()
        p.text = ""
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run = p.add_run(f"{bp.title}  ·  ")
        run.font.size = Pt(8)
        run.font.color.rgb = RGBColor(*rgb(theme.muted))
        _field(p, "PAGE", "1")
        run2 = p.add_run(" of ")
        run2.font.size = Pt(8)
        run2.font.color.rgb = RGBColor(*rgb(theme.muted))
        _field(p, "NUMPAGES", "1")
        for r in p.runs:
            r.font.size = Pt(8)
            r.font.color.rgb = RGBColor(*rgb(theme.muted))


def _add_table(doc: Document, tbl: Table, theme: Theme, caption_no: int) -> None:
    kinds = [column_kind([r[i] if i < len(r) else None for r in tbl.rows],
                         [str(r[i]) if i < len(r) and r[i] is not None else "" for r in tbl.rows])
             for i in range(tbl.n_cols)]

    table = doc.add_table(rows=1, cols=tbl.n_cols)
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.autofit = True

    hdr = table.rows[0]
    for i, name in enumerate(tbl.headers):
        cell = hdr.cells[i]
        cell.text = ""
        run = cell.paragraphs[0].add_run(str(name))
        run.font.bold = True
        run.font.size = Pt(9.5)
        run.font.color.rgb = RGBColor(*rgb(theme.ink))
        cell.paragraphs[0].alignment = (
            WD_ALIGN_PARAGRAPH.RIGHT if kinds[i] in ("number", "currency", "percent")
            else WD_ALIGN_PARAGRAPH.LEFT)
        _shade(cell, theme.accent_soft)
        _cell_border(cell, "bottom", theme.accent, 8)
    _repeat_header(hdr)

    for r_i, row in enumerate(tbl.rows):
        cells = table.add_row().cells
        for i in range(tbl.n_cols):
            value = row[i] if i < len(row) else None
            cell = cells[i]
            cell.text = ""
            run = cell.paragraphs[0].add_run(fmt_value(value, kinds[i]))
            run.font.size = Pt(9.5)
            run.font.color.rgb = RGBColor(*rgb(theme.body))
            cell.paragraphs[0].alignment = (
                WD_ALIGN_PARAGRAPH.RIGHT if kinds[i] in ("number", "currency", "percent")
                else WD_ALIGN_PARAGRAPH.LEFT)
            if r_i % 2 == 1:
                _shade(cell, theme.surface)
            _cell_border(cell, "bottom", theme.rule, 4)

    cap = doc.add_paragraph(style="Caption")
    cap.add_run(f"Table {caption_no}. {tbl.caption or tbl.name}")
    cap.paragraph_format.space_after = Pt(14)


def build(bp: Blueprint, out_path: str | Path, theme_name: str = "slate",
          toc: bool = True) -> Path:
    """Render the blueprint as a Word document and return the written path."""
    theme = get_theme(theme_name)
    doc = Document()
    _page_setup(doc)
    _setup_styles(doc, theme)

    core = doc.core_properties
    core.title = bp.title
    core.author = bp.author or "OfficeMind"
    core.comments = f"Generated by OfficeMind from {bp.source}"

    # ---- cover ----------------------------------------------------------
    doc.add_paragraph()
    t = doc.add_paragraph(bp.title, style="Title")
    t.paragraph_format.space_after = Pt(2)
    sub = doc.add_paragraph()
    run = sub.add_run(bp.subtitle or bp.date)
    run.font.size = Pt(12)
    run.font.color.rgb = RGBColor(*rgb(theme.muted))
    sub.paragraph_format.space_after = Pt(18)

    if bp.facts:
        ft = doc.add_table(rows=0, cols=2)
        for k, v in list(bp.facts.items())[:10]:
            cells = ft.add_row().cells
            kr = cells[0].paragraphs[0].add_run(k)
            kr.font.bold = True
            kr.font.size = Pt(9.5)
            kr.font.color.rgb = RGBColor(*rgb(theme.muted))
            vr = cells[1].paragraphs[0].add_run(str(v))
            vr.font.size = Pt(9.5)
            vr.font.color.rgb = RGBColor(*rgb(theme.body))
            cells[0].width = Inches(1.8)
            cells[1].width = Inches(4.4)
        doc.add_paragraph()

    if bp.author:
        a = doc.add_paragraph()
        ar = a.add_run(f"Prepared by {bp.author}  ·  {bp.date}")
        ar.font.size = Pt(9.5)
        ar.font.color.rgb = RGBColor(*rgb(theme.muted))

    # ---- contents -------------------------------------------------------
    if toc and len(bp.sections) >= 3:
        doc.add_paragraph().add_run().add_break(WD_BREAK.PAGE)
        doc.add_paragraph("Contents", style="Heading 1")
        p = doc.add_paragraph()
        _field(p, 'TOC \\o "1-3" \\h \\z \\u', "Right-click and choose Update Field to build the contents.")
        _update_fields_on_open(doc)

    doc.add_paragraph().add_run().add_break(WD_BREAK.PAGE)

    # ---- executive summary ---------------------------------------------
    if bp.summary:
        doc.add_paragraph("Executive summary", style="Heading 1")
        for item in bp.summary:
            p = doc.add_paragraph(item, style="List Bullet")
            p.paragraph_format.space_after = Pt(4)
        doc.add_paragraph()

    # ---- body -----------------------------------------------------------
    caption_no = 1
    seen_summary = False
    for sec in bp.sections:
        low = sec.heading.lower()
        if bp.summary and not seen_summary and "summary" in low:
            seen_summary = True
            continue
        style = f"Heading {min(max(sec.level, 1), 3)}"
        doc.add_paragraph(sec.heading or "Section", style=style)
        for para in sec.paragraphs:
            doc.add_paragraph(para)
        for b in sec.bullets:
            doc.add_paragraph(b, style="List Bullet")
        for tbl in sec.tables:
            _add_table(doc, tbl, theme, caption_no)
            caption_no += 1

    for tbl in bp.tables:
        doc.add_paragraph(tbl.name or "Data", style="Heading 1")
        _add_table(doc, tbl, theme, caption_no)
        caption_no += 1

    # ---- next steps -----------------------------------------------------
    if bp.next_steps:
        doc.add_paragraph("Next steps", style="Heading 1")
        for i, step in enumerate(bp.next_steps, 1):
            p = doc.add_paragraph(style="List Number")
            p.add_run(step)

    _footer(doc, bp, theme)

    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    doc.save(out)
    return out
