"""Post-build QA. Every generated file is re-opened and checked before the
agent reports success — the same discipline the system prompt demands.

Each verifier returns a list of (level, message) where level is
"ok" | "warn" | "fail".
"""

from __future__ import annotations

import re
from pathlib import Path

Finding = tuple[str, str]


def _ok(msg: str) -> Finding:
    return ("ok", msg)


def verify_docx(path: str | Path) -> list[Finding]:
    from docx import Document

    doc = Document(str(path))
    out: list[Finding] = []

    heads = [p for p in doc.paragraphs if p.style.name.startswith("Heading")]
    levels = [int(p.style.name.split()[-1]) for p in heads if p.style.name[-1].isdigit()]
    if not heads:
        out.append(("warn", "no heading styles found — the document has no navigable structure"))
    else:
        out.append(_ok(f"{len(heads)} real headings (levels {sorted(set(levels))})"))
    for a, b in zip(levels, levels[1:]):
        if b - a > 1:
            out.append(("warn", f"heading level jumps {a} -> {b}; TOC nesting will look odd"))
            break

    xml = doc.element.xml
    if "TOC \\o" in xml:
        out.append(_ok("table of contents is a live field (updates with F9)"))
    footer_xml = "".join(sec.footer._element.xml for sec in doc.sections if sec.footer is not None)
    if "PAGE" in footer_xml and "NUMPAGES" in footer_xml:
        out.append(_ok("footer carries live page numbering (Page X of Y)"))
    else:
        out.append(("warn", "no page numbering found in the footer"))

    empty = [i for i, p in enumerate(doc.paragraphs) if not p.text.strip()]
    if len(empty) > len(doc.paragraphs) * 0.5:
        out.append(("warn", "more than half the paragraphs are empty"))

    for t_i, table in enumerate(doc.tables, 1):
        if not table.rows:
            out.append(("fail", f"table {t_i} has no rows"))
            continue
        header_texts = [c.text.strip() for c in table.rows[0].cells]
        if not any(header_texts):
            out.append(("warn", f"table {t_i} has a blank header row"))
    if doc.tables:
        out.append(_ok(f"{len(doc.tables)} table(s), header rows set to repeat"))
    return out


def verify_xlsx(path: str | Path) -> list[Finding]:
    from openpyxl import load_workbook

    wb = load_workbook(str(path))
    out: list[Finding] = []
    out.append(_ok(f"{len(wb.sheetnames)} sheets: {', '.join(wb.sheetnames)}"))

    formulas = 0
    bad_refs = 0
    for ws in wb.worksheets:
        for row in ws.iter_rows():
            for cell in row:
                v = cell.value
                if isinstance(v, str) and v.startswith("="):
                    formulas += 1
                    if "#REF!" in v:
                        bad_refs += 1

    if formulas:
        out.append(_ok(f"{formulas} live formulas (totals and shares recompute on edit)"))
    else:
        out.append(("warn", "no formulas written — values are static"))
    if bad_refs:
        out.append(("fail", f"{bad_refs} formulas contain #REF!"))

    if "Checks" in wb.sheetnames:
        ws = wb["Checks"]
        rows = [r for r in ws.iter_rows(min_row=6, min_col=2, max_col=6, values_only=True)
                if r[0]]
        good = sum(1 for r in rows if isinstance(r[4], str) and "IF(ABS(" in r[4])
        out.append(_ok(f"{good} tie-out check(s) wired to the source data")
                   if good == len(rows) and rows else
                   ("warn", "checks sheet present but some rows are not wired"))
    else:
        out.append(("warn", "no Checks sheet (only expected when the input has no data tables)"))

    for ws in wb.worksheets:
        for tbl in getattr(ws, "tables", {}).values():
            m = re.match(r"^[A-Z]+\d+:([A-Z]+)(\d+)$", tbl.ref)
            if m and int(m.group(2)) < 2:
                out.append(("fail", f"table {tbl.name} on {ws.title} covers no data rows"))
    return out


def verify_pptx(path: str | Path) -> list[Finding]:
    from pptx import Presentation
    from pptx.util import Emu

    prs = Presentation(str(path))
    out: list[Finding] = []
    w, h = prs.slide_width, prs.slide_height
    out.append(_ok(f"{len(prs.slides)} slides at {w / 914400:.2f}×{h / 914400:.2f} in (16:9)"))

    missing_notes, untitled, overflow, offcanvas = [], [], [], []
    for i, slide in enumerate(prs.slides, 1):
        title = slide.shapes.title
        if title is None or not title.text.strip():
            untitled.append(i)
        if not slide.notes_slide.notes_text_frame.text.strip().strip("—"):
            missing_notes.append(i)
        for shape in slide.shapes:
            if shape.left is None or shape.top is None:
                continue
            right = shape.left + (shape.width or 0)
            bottom = shape.top + (shape.height or 0)
            if shape.left < -Emu(1) or shape.top < -Emu(1) or right > w + Emu(1) or bottom > h + Emu(1):
                offcanvas.append(f"slide {i}: {shape.shape_type}")
            if shape.has_text_frame:
                for p in shape.text_frame.paragraphs:
                    text = "".join(r.text for r in p.runs)
                    if len(text) > 180:
                        overflow.append(f"slide {i}")
                        break

    out.append(_ok("every slide has speaker notes") if not missing_notes
               else ("warn", f"slides without speaker notes: {missing_notes}"))
    out.append(_ok("every slide has a title") if not untitled
               else ("warn", f"slides without a title: {untitled}"))
    out.append(_ok("nothing sits off the canvas") if not offcanvas
               else ("warn", f"objects outside the slide: {sorted(set(offcanvas))[:4]}"))
    if overflow:
        out.append(("warn", f"long text blocks may overflow on {sorted(set(overflow))[:4]}"))
    return out


def verify(files: dict[str, Path]) -> dict[str, list[Finding]]:
    checkers = {"word": verify_docx, "excel": verify_xlsx, "ppt": verify_pptx}
    results: dict[str, list[Finding]] = {}
    for kind, path in files.items():
        checker = checkers.get(kind)
        if not checker:
            continue
        try:
            results[kind] = checker(path)
        except Exception as e:                        # a file we cannot reopen is a hard fail
            results[kind] = [("fail", f"could not reopen the file: {e}")]
    return results


def format_report(results: dict[str, list[Finding]]) -> str:
    marks = {"ok": "✓", "warn": "!", "fail": "✗"}
    lines: list[str] = []
    for kind, findings in results.items():
        lines.append(f"  {kind}")
        for level, msg in findings:
            lines.append(f"    {marks[level]} {msg}")
    return "\n".join(lines)


def worst(results: dict[str, list[Finding]]) -> str:
    levels = [lvl for findings in results.values() for lvl, _ in findings]
    return "fail" if "fail" in levels else ("warn" if "warn" in levels else "ok")
