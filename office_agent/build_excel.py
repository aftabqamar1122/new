"""Blueprint -> .xlsx  (typed data, live formulas, chart, tie-out checks)."""

from __future__ import annotations

import re
from datetime import date, datetime
from pathlib import Path

from openpyxl import Workbook
from openpyxl.chart import BarChart, Reference
from openpyxl.formatting.rule import DataBarRule
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.table import Table as XLTable, TableStyleInfo
from openpyxl.worksheet.worksheet import Worksheet

from .model import Blueprint, Table
from .parse import column_kind
from .theme import Theme, get_theme

NUM_FORMATS = {
    "currency": "#,##0.00",
    "number": "#,##0.00",
    "integer": "#,##0",
    "percent": "0.0%",
    "date": "dd-mmm-yyyy",
    "text": "General",
}


def _safe_sheet_name(name: str, used: set[str]) -> str:
    clean = re.sub(r"[\[\]:*?/\\]", " ", (name or "Sheet")).strip()[:31] or "Sheet"
    base, i = clean, 2
    while clean.lower() in used:
        suffix = f" {i}"
        clean = base[: 31 - len(suffix)] + suffix
        i += 1
    used.add(clean.lower())
    return clean


def _safe_table_name(name: str, used: set[str]) -> str:
    clean = re.sub(r"\W", "_", name or "Data")
    if not clean or clean[0].isdigit():
        clean = "T_" + clean
    base, i = clean, 2
    while clean.lower() in used:
        clean = f"{base}_{i}"
        i += 1
    used.add(clean.lower())
    return clean[:64]


def _kinds(tbl: Table) -> list[str]:
    out = []
    for i in range(tbl.n_cols):
        vals = [r[i] if i < len(r) else None for r in tbl.rows]
        raws = [str(v) if v is not None else "" for v in vals]
        kind = column_kind(vals, raws)
        if kind == "number" and all(v is None or isinstance(v, int) or
                                    (isinstance(v, float) and float(v).is_integer()) for v in vals):
            kind = "integer"
        out.append(kind)
    return out


def _style_header(ws: Worksheet, row: int, n_cols: int, theme: Theme,
                  start_col: int = 1) -> None:
    fill = PatternFill("solid", fgColor=theme.accent)
    for c in range(start_col, n_cols + 1):
        cell = ws.cell(row=row, column=c)
        cell.font = Font(name=theme.body_font, bold=True, size=10, color="FFFFFF")
        cell.fill = fill
        cell.alignment = Alignment(horizontal="left", vertical="center", wrap_text=True)
        cell.border = Border(bottom=Side("thin", color=theme.ink))
    ws.row_dimensions[row].height = 22


def _autosize(ws: Worksheet, tbl: Table, start_col: int = 1) -> None:
    for i in range(tbl.n_cols):
        longest = len(str(tbl.headers[i] if i < len(tbl.headers) else ""))
        for row in tbl.rows[:200]:
            v = row[i] if i < len(row) else None
            if isinstance(v, (date, datetime)):
                longest = max(longest, 11)
            elif v is not None:
                longest = max(longest, len(f"{v:,.2f}" if isinstance(v, float) else str(v)))
        ws.column_dimensions[get_column_letter(start_col + i)].width = min(max(longest + 3, 10), 42)


def _write_table(ws: Worksheet, tbl: Table, theme: Theme, table_names: set[str],
                 start_row: int = 1) -> tuple[int, int, list[str]]:
    """Write headers+rows as a real Excel Table. Returns (first_data_row, last_row, kinds)."""
    kinds = _kinds(tbl)
    for i, h in enumerate(tbl.headers, start=1):
        ws.cell(row=start_row, column=i, value=str(h))
    _style_header(ws, start_row, tbl.n_cols, theme)

    for r, row in enumerate(tbl.rows, start=start_row + 1):
        for i in range(tbl.n_cols):
            value = row[i] if i < len(row) else None
            cell = ws.cell(row=r, column=i + 1, value=value)
            cell.font = Font(name=theme.body_font, size=10, color=theme.body)
            cell.number_format = NUM_FORMATS[kinds[i]]
            cell.alignment = Alignment(
                horizontal="right" if kinds[i] in ("number", "integer", "currency", "percent")
                else ("center" if kinds[i] == "date" else "left"))

    last_row = start_row + tbl.n_rows
    ref = f"A{start_row}:{get_column_letter(tbl.n_cols)}{last_row}"
    xt = XLTable(displayName=_safe_table_name(tbl.name, table_names), ref=ref)
    xt.tableStyleInfo = TableStyleInfo(name="TableStyleLight1", showRowStripes=True)
    ws.add_table(xt)
    ws.freeze_panes = ws.cell(row=start_row + 1, column=1)
    _autosize(ws, tbl)
    return start_row + 1, last_row, kinds


def _label(ws: Worksheet, row: int, col: int, text: str, theme: Theme,
           size: int = 10, bold: bool = False, color: str | None = None) -> None:
    cell = ws.cell(row=row, column=col, value=text)
    cell.font = Font(name=theme.body_font, size=size, bold=bold, color=color or theme.body)


def _cover(wb: Workbook, bp: Blueprint, theme: Theme, index: list[tuple[str, str]]) -> None:
    ws = wb.create_sheet("Cover", 0)
    ws.sheet_view.showGridLines = False
    ws.column_dimensions["A"].width = 3
    ws.column_dimensions["B"].width = 26
    ws.column_dimensions["C"].width = 62

    ws["B2"] = bp.title
    ws["B2"].font = Font(name=theme.heading_font, size=22, bold=True, color=theme.ink)
    ws["B3"] = bp.subtitle or bp.date
    ws["B3"].font = Font(name=theme.body_font, size=11, color=theme.muted)

    row = 5
    meta = {"Prepared by": bp.author or "OfficeMind", "Date": bp.date, "Source": bp.source}
    meta.update(bp.facts)
    for k, v in list(meta.items())[:14]:
        _label(ws, row, 2, str(k), theme, bold=True, color=theme.muted)
        _label(ws, row, 3, str(v), theme)
        row += 1

    row += 1
    _label(ws, row, 2, "Contents", theme, size=13, bold=True, color=theme.accent)
    row += 1
    for sheet_name, purpose in index:
        cell = ws.cell(row=row, column=2, value=sheet_name)
        cell.font = Font(name=theme.body_font, size=10, bold=True, color=theme.accent,
                         underline="single")
        cell.hyperlink = f"#'{sheet_name}'!A1"
        _label(ws, row, 3, purpose, theme, color=theme.muted)
        row += 1

    if bp.summary:
        row += 1
        _label(ws, row, 2, "Key points", theme, size=13, bold=True, color=theme.accent)
        row += 1
        for item in bp.summary:
            _label(ws, row, 2, "•", theme, color=theme.accent)
            cell = ws.cell(row=row, column=3, value=item)
            cell.font = Font(name=theme.body_font, size=10, color=theme.body)
            cell.alignment = Alignment(wrap_text=True, vertical="top")
            row += 1


def _analysis(wb: Workbook, data_ws: Worksheet, tbl: Table, kinds: list[str],
              first_row: int, last_row: int, theme: Theme, used: set[str],
              table_names: set[str]) -> str | None:
    """Group the first text column by the numeric columns, with live SUMIF formulas."""
    try:
        key_idx = next(i for i, k in enumerate(kinds) if k == "text")
    except StopIteration:
        return None
    num_idx = [i for i, k in enumerate(kinds) if k in ("number", "integer", "currency", "percent")]
    if not num_idx:
        return None

    groups: list[str] = []
    for row in tbl.rows:
        v = row[key_idx] if key_idx < len(row) else None
        if v is not None and str(v) not in groups:
            groups.append(str(v))
    if len(groups) < 2 or len(groups) > 60:
        return None

    name = _safe_sheet_name(f"Analysis {tbl.name}"[:31], used)
    ws = wb.create_sheet(name)
    ws.sheet_view.showGridLines = False
    src = data_ws.title
    key_col = get_column_letter(key_idx + 1)
    key_range = f"'{src}'!${key_col}${first_row}:${key_col}${last_row}"

    ws["B2"] = f"{tbl.name} — summary by {tbl.headers[key_idx]}"
    ws["B2"].font = Font(name=theme.heading_font, size=15, bold=True, color=theme.ink)
    ws["B3"] = f"Every figure below is a live SUMIF against '{src}'. Change the data and these update."
    ws["B3"].font = Font(name=theme.body_font, size=9, italic=True, color=theme.muted)

    head_row = 5
    ws.cell(row=head_row, column=2, value=tbl.headers[key_idx])
    for j, i in enumerate(num_idx):
        ws.cell(row=head_row, column=3 + j, value=tbl.headers[i])
    share_col = 3 + len(num_idx)
    ws.cell(row=head_row, column=share_col, value=f"% of total {tbl.headers[num_idx[0]]}")
    _style_header(ws, head_row, share_col, theme, start_col=2)

    r = head_row + 1
    for g in groups:
        ws.cell(row=r, column=2, value=g).font = Font(name=theme.body_font, size=10, color=theme.body)
        for j, i in enumerate(num_idx):
            col = get_column_letter(i + 1)
            rng = f"'{src}'!${col}${first_row}:${col}${last_row}"
            cell = ws.cell(row=r, column=3 + j, value=f"=SUMIF({key_range},$B{r},{rng})")
            cell.number_format = NUM_FORMATS["currency" if kinds[i] == "currency" else
                                             ("percent" if kinds[i] == "percent" else "integer"
                                              if kinds[i] == "integer" else "number")]
            cell.font = Font(name=theme.body_font, size=10, color=theme.body)
        r += 1
    last_g = r - 1

    total_row = r
    ws.cell(row=total_row, column=2, value="Total").font = Font(
        name=theme.body_font, size=10, bold=True, color=theme.ink)
    for j in range(len(num_idx)):
        col = get_column_letter(3 + j)
        cell = ws.cell(row=total_row, column=3 + j,
                       value=f"=SUM({col}{head_row + 1}:{col}{last_g})")
        cell.font = Font(name=theme.body_font, size=10, bold=True, color=theme.ink)
        cell.number_format = ws.cell(row=head_row + 1, column=3 + j).number_format
        cell.border = Border(top=Side("thin", color=theme.ink))

    first_num_col = get_column_letter(3)
    share_letter = get_column_letter(share_col)
    for rr in range(head_row + 1, last_g + 1):
        cell = ws.cell(row=rr, column=share_col,
                       value=f"=IF(${first_num_col}${total_row}=0,0,{first_num_col}{rr}/${first_num_col}${total_row})")
        cell.number_format = "0.0%"
        cell.font = Font(name=theme.body_font, size=10, color=theme.muted)
    ws.conditional_formatting.add(
        f"{share_letter}{head_row + 1}:{share_letter}{last_g}",
        DataBarRule(start_type="num", start_value=0, end_type="num", end_value=1,
                    color=theme.accent, showValue=True))

    ws.column_dimensions["A"].width = 3
    ws.column_dimensions["B"].width = 28
    for c in range(3, share_col + 1):
        ws.column_dimensions[get_column_letter(c)].width = 16

    chart = BarChart()
    chart.type = "bar"
    chart.style = 2
    chart.title = f"{tbl.headers[num_idx[0]]} by {tbl.headers[key_idx]}"
    chart.y_axis.title = None
    chart.x_axis.title = None
    data = Reference(ws, min_col=3, min_row=head_row, max_row=last_g)
    cats = Reference(ws, min_col=2, min_row=head_row + 1, max_row=last_g)
    chart.add_data(data, titles_from_data=True)
    chart.set_categories(cats)
    chart.height, chart.width = 1.2 + 0.35 * len(groups), 16
    chart.legend = None
    if chart.series:
        chart.series[0].graphicalProperties.solidFill = theme.accent
        chart.series[0].graphicalProperties.line.noFill = True
    ws.add_chart(chart, f"B{total_row + 3}")
    return name


def _checks(wb: Workbook, theme: Theme, rows: list[tuple[str, str, str]]) -> None:
    ws = wb.create_sheet("Checks")
    ws.sheet_view.showGridLines = False
    ws["B2"] = "Integrity checks"
    ws["B2"].font = Font(name=theme.heading_font, size=15, bold=True, color=theme.ink)
    ws["B3"] = "Every row must read OK. A CHECK means the analysis no longer ties to the source data."
    ws["B3"].font = Font(name=theme.body_font, size=9, italic=True, color=theme.muted)

    head = 5
    for j, h in enumerate(["Check", "Source", "Analysis", "Difference", "Status"], start=2):
        ws.cell(row=head, column=j, value=h)
    _style_header(ws, head, 6, theme, start_col=2)

    r = head + 1
    for label, source_formula, analysis_formula in rows:
        ws.cell(row=r, column=2, value=label).font = Font(name=theme.body_font, size=10, color=theme.body)
        for col, formula in ((3, source_formula), (4, analysis_formula)):
            cell = ws.cell(row=r, column=col, value=formula)
            cell.number_format = "#,##0.00"
            cell.font = Font(name=theme.body_font, size=10, color=theme.body)
        d = ws.cell(row=r, column=5, value=f"=C{r}-D{r}")
        d.number_format = "#,##0.00"
        d.font = Font(name=theme.body_font, size=10, color=theme.body)
        st = ws.cell(row=r, column=6, value=f'=IF(ABS(E{r})<0.01,"OK","CHECK")')
        st.font = Font(name=theme.body_font, size=10, bold=True, color=theme.good)
        st.alignment = Alignment(horizontal="center")
        r += 1

    ws.column_dimensions["A"].width = 3
    ws.column_dimensions["B"].width = 46
    for c in "CDEF":
        ws.column_dimensions[c].width = 16


def _notes_sheet(wb: Workbook, bp: Blueprint, theme: Theme, used: set[str]) -> str:
    ws = wb.create_sheet(_safe_sheet_name("Notes", used))
    ws.sheet_view.showGridLines = False
    ws.column_dimensions["A"].width = 3
    ws.column_dimensions["B"].width = 30
    ws.column_dimensions["C"].width = 90
    r = 2
    for sec in bp.sections:
        _label(ws, r, 2, sec.heading, theme, size=12, bold=True, color=theme.accent)
        r += 1
        for para in sec.paragraphs:
            cell = ws.cell(row=r, column=3, value=para)
            cell.alignment = Alignment(wrap_text=True, vertical="top")
            cell.font = Font(name=theme.body_font, size=10, color=theme.body)
            r += 1
        for b in sec.bullets:
            _label(ws, r, 2, "•", theme, color=theme.accent)
            cell = ws.cell(row=r, column=3, value=b)
            cell.font = Font(name=theme.body_font, size=10, color=theme.body)
            cell.alignment = Alignment(wrap_text=True, vertical="top")
            r += 1
        r += 1
    return ws.title


def build(bp: Blueprint, out_path: str | Path, theme_name: str = "slate") -> Path:
    """Render the blueprint as a workbook and return the written path."""
    theme = get_theme(theme_name)
    wb = Workbook()
    wb.remove(wb.active)

    used_sheets: set[str] = {"cover", "checks"}
    table_names: set[str] = set()
    index: list[tuple[str, str]] = []
    check_rows: list[tuple[str, str, str]] = []

    tables = [t for t in bp.all_tables if t.n_rows and t.n_cols >= 2]
    for tbl in tables:
        ws = wb.create_sheet(_safe_sheet_name(tbl.name or "Data", used_sheets))
        first_row, last_row, kinds = _write_table(ws, tbl, theme, table_names)
        index.append((ws.title, f"{tbl.n_rows} rows × {tbl.n_cols} columns of source data"))

        analysis_name = _analysis(wb, ws, tbl, kinds, first_row, last_row, theme,
                                  used_sheets, table_names)
        if analysis_name:
            index.append((analysis_name, "Grouped summary with live SUMIF formulas and a chart"))
            a_ws = wb[analysis_name]
            num_idx = [i for i, k in enumerate(kinds)
                       if k in ("number", "integer", "currency", "percent")]
            for j, i in enumerate(num_idx):
                col = get_column_letter(i + 1)
                a_col = get_column_letter(3 + j)
                total_row = a_ws.max_row
                while a_ws.cell(row=total_row, column=2).value != "Total" and total_row > 1:
                    total_row -= 1
                check_rows.append((
                    f"{ws.title} · {tbl.headers[i]} ties to {analysis_name}",
                    f"=SUM('{ws.title}'!{col}{first_row}:{col}{last_row})",
                    f"='{analysis_name}'!{a_col}{total_row}",
                ))

    if not tables:
        name = _notes_sheet(wb, bp, theme, used_sheets)
        index.append((name, "Structured notes parsed from the raw input"))

    if check_rows:
        _checks(wb, theme, check_rows)
        index.append(("Checks", "Tie-outs between source data and every analysis"))

    _cover(wb, bp, theme, index)
    wb.active = 0

    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    wb.save(out)
    return out
