"""Tests for the OfficeMind generator. Run: python3 -m unittest discover -s tests -v"""

import re
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from office_agent import generate, parse                       # noqa: E402
from office_agent import build_excel, build_ppt, build_word, llm, verify  # noqa: E402
from office_agent.cli import decide_targets, slug              # noqa: E402
from office_agent.parse import coerce, column_kind             # noqa: E402

REPORT = """Q3 Site Progress Report
Project: Almeria Tower
Prepared by: A. Qamar
Date: 15-Aug-2026

EXECUTIVE SUMMARY
- Concrete works are 12% ahead of plan
- Manpower cost is 8% over budget

1. Manpower
Average deployed headcount rose from 240 to 268 across the quarter.

Region, Planned, Actual, Cost
North, 120, 138, 412000
South, 60, 55, 168500
East, 60, 75, 244300

2. Risks
- Rebar delivery slipping by 2 weeks

Next Steps
- Confirm rebar PO by 5 Sep
- Re-baseline the manpower plan
"""


class TestCoercion(unittest.TestCase):
    def test_numbers_and_currency(self):
        self.assertEqual(coerce("1,234"), 1234)
        self.assertEqual(coerce("$1,234.50"), 1234.5)
        self.assertEqual(coerce("412000"), 412000)
        self.assertEqual(coerce("(2,500)"), -2500)
        self.assertEqual(coerce("SAR 900"), 900)

    def test_percent_and_dates(self):
        self.assertAlmostEqual(coerce("12%"), 0.12)
        self.assertEqual(coerce("15-Aug-2026"), date(2026, 8, 15))
        self.assertEqual(coerce("2026-01-05"), date(2026, 1, 5))

    def test_blanks_and_text(self):
        for blank in ("", "  ", "-", "N/A", None):
            self.assertIsNone(coerce(blank))
        self.assertEqual(coerce("North"), "North")

    def test_column_kind(self):
        self.assertEqual(column_kind([1, 2, 3], ["1", "2", "3"]), "number")
        self.assertEqual(column_kind([0.1, 0.2], ["10%", "20%"]), "percent")
        self.assertEqual(column_kind(["a", "b"], ["a", "b"]), "text")


class TestParser(unittest.TestCase):
    def setUp(self):
        self.bp = parse(REPORT)

    def test_metadata(self):
        self.assertEqual(self.bp.title, "Q3 Site Progress Report")
        self.assertEqual(self.bp.author, "A. Qamar")
        self.assertEqual(self.bp.date, "15-Aug-2026")
        self.assertEqual(self.bp.facts.get("Project"), "Almeria Tower")

    def test_sections_and_bullets(self):
        headings = [s.heading for s in self.bp.sections]
        self.assertIn("Executive Summary", headings)
        self.assertIn("Manpower", headings)
        self.assertIn("Risks", headings)
        self.assertIn("Next Steps", headings)
        risks = next(s for s in self.bp.sections if s.heading == "Risks")
        self.assertEqual(risks.bullets, ["Rebar delivery slipping by 2 weeks"])

    def test_summary_and_next_steps(self):
        self.assertEqual(len(self.bp.summary), 2)
        self.assertEqual(len(self.bp.next_steps), 2)
        self.assertIn("Confirm rebar PO by 5 Sep", self.bp.next_steps)

    def test_table_extraction_and_typing(self):
        tables = self.bp.all_tables
        self.assertEqual(len(tables), 1)
        t = tables[0]
        self.assertEqual(t.headers, ["Region", "Planned", "Actual", "Cost"])
        self.assertEqual(t.n_rows, 3)
        self.assertEqual(t.rows[0], ["North", 120, 138, 412000])
        self.assertTrue(all(isinstance(r[3], int) for r in t.rows))

    def test_pipe_and_tab_tables(self):
        pipe = parse("| Item | Qty |\n|---|---|\n| Cement | 200 |\n| Rebar | 80 |\n")
        self.assertEqual(pipe.all_tables[0].headers, ["Item", "Qty"])
        self.assertEqual(pipe.all_tables[0].n_rows, 2)
        tab = parse("Region\tQ1\tQ2\nAPAC\t120\t180\nEMEA\t210\t190\n")
        self.assertEqual(tab.all_tables[0].n_rows, 2)

    def test_prose_only_has_no_tables(self):
        bp = parse("Notes\n\nWe met on Tuesday. The vendor agreed to the new terms.\n")
        self.assertFalse(bp.has_data)
        self.assertTrue(bp.sections)

    def test_title_fallback_for_pure_data(self):
        bp = parse("a,b\n1,2\n3,4\n", source="q3_export.csv")
        self.assertEqual(bp.title, "Q3 Export")

    def test_empty_input_does_not_raise(self):
        bp = parse("")
        self.assertEqual(bp.sections, [])
        self.assertFalse(bp.has_data)


class TestWord(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.path = build_word.build(parse(REPORT), Path(cls.tmp.name) / "r.docx")

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_structure(self):
        from docx import Document
        doc = Document(str(self.path))
        styles = [p.style.name for p in doc.paragraphs]
        self.assertIn("Title", styles)
        self.assertIn("Heading 1", styles)
        self.assertIn("List Bullet", styles)
        self.assertGreaterEqual(len(doc.tables), 1)

    def test_live_fields(self):
        from docx import Document
        doc = Document(str(self.path))
        self.assertIn("TOC \\o", doc.element.xml)
        footers = "".join(s.footer._element.xml for s in doc.sections)
        self.assertIn("NUMPAGES", footers)

    def test_data_table_values_render(self):
        from docx import Document
        doc = Document(str(self.path))
        data_table = doc.tables[-1]
        texts = [c.text for c in data_table.rows[1].cells]
        self.assertIn("North", texts)
        self.assertIn("412,000", texts)

    def test_verifier_passes(self):
        findings = verify.verify_docx(self.path)
        self.assertFalse([f for f in findings if f[0] == "fail"])


class TestExcel(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.path = build_excel.build(parse(REPORT), Path(cls.tmp.name) / "r.xlsx")

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def setUp(self):
        from openpyxl import load_workbook
        self.wb = load_workbook(str(self.path))

    def test_sheets(self):
        self.assertIn("Cover", self.wb.sheetnames)
        self.assertIn("Checks", self.wb.sheetnames)
        self.assertTrue(any(n.startswith("Analysis") for n in self.wb.sheetnames))

    def test_data_is_typed_not_text(self):
        ws = self.wb["Manpower"]
        self.assertEqual(ws["A1"].value, "Region")
        self.assertEqual(ws["D2"].value, 412000)
        self.assertIsInstance(ws["B2"].value, int)

    def test_sumif_covers_every_data_row(self):
        ws = self.wb[next(n for n in self.wb.sheetnames if n.startswith("Analysis"))]
        formulas = [c.value for row in ws.iter_rows() for c in row
                    if isinstance(c.value, str) and c.value.startswith("=SUMIF")]
        self.assertTrue(formulas)
        for f in formulas:
            ranges = re.findall(r"\$([A-Z]+)\$(\d+):\$[A-Z]+\$(\d+)", f)
            for _, first, last in ranges:
                self.assertEqual(int(first), 2)      # data starts under the header
                self.assertEqual(int(last), 4)       # three data rows -> row 4

    def test_totals_and_share_formulas(self):
        ws = self.wb[next(n for n in self.wb.sheetnames if n.startswith("Analysis"))]
        col_b = [ws.cell(row=r, column=2).value for r in range(1, ws.max_row + 1)]
        self.assertIn("Total", col_b)
        total_row = col_b.index("Total") + 1
        self.assertEqual(ws.cell(row=total_row, column=3).value, "=SUM(C6:C8)")
        share = ws.cell(row=6, column=6).value
        self.assertIsInstance(share, str)
        self.assertTrue(share.startswith("=IF("))

    def test_checks_tie_to_the_analysis(self):
        ws = self.wb["Checks"]
        rows = [r for r in ws.iter_rows(min_row=6, min_col=2, max_col=6, values_only=True) if r[0]]
        self.assertEqual(len(rows), 3)
        for label, source, analysis, diff, status in rows:
            self.assertTrue(source.startswith("=SUM("))
            self.assertTrue(analysis.startswith("='Analysis"))
            self.assertTrue(status.startswith("=IF(ABS("))

    def test_no_broken_references(self):
        for ws in self.wb.worksheets:
            for row in ws.iter_rows():
                for cell in row:
                    if isinstance(cell.value, str):
                        self.assertNotIn("#REF!", cell.value)

    def test_prose_only_input_gets_a_notes_sheet(self):
        with tempfile.TemporaryDirectory() as d:
            p = build_excel.build(parse("Notes\n\nSection A\n- one\n- two\n"), Path(d) / "n.xlsx")
            from openpyxl import load_workbook
            wb = load_workbook(str(p))
            self.assertIn("Notes", wb.sheetnames)


class TestPowerPoint(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.path = build_ppt.build(parse(REPORT), Path(cls.tmp.name) / "r.pptx")

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def setUp(self):
        from pptx import Presentation
        self.prs = Presentation(str(self.path))

    def test_widescreen_and_slide_count(self):
        self.assertAlmostEqual(self.prs.slide_width / self.prs.slide_height, 16 / 9, places=2)
        self.assertGreaterEqual(len(self.prs.slides), 5)

    def test_every_slide_has_title_and_notes(self):
        for i, slide in enumerate(self.prs.slides, 1):
            self.assertIsNotNone(slide.shapes.title, f"slide {i} has no title placeholder")
            self.assertTrue(slide.shapes.title.text.strip(), f"slide {i} title is empty")
            self.assertTrue(slide.notes_slide.notes_text_frame.text.strip(),
                            f"slide {i} has no speaker notes")

    def test_next_steps_appear_once(self):
        titles = [s.shapes.title.text.lower() for s in self.prs.slides]
        self.assertEqual(sum(1 for t in titles if t.startswith("next step")), 1)

    def test_chart_slide_title_is_an_assertion(self):
        titles = [s.shapes.title.text for s in self.prs.slides]
        self.assertTrue(any("accounts for" in t for t in titles), titles)

    def test_nothing_off_canvas(self):
        findings = verify.verify_pptx(self.path)
        self.assertFalse([f for f in findings if f[0] == "fail"])


class TestTargeting(unittest.TestCase):
    def test_explicit_beats_auto(self):
        bp = parse(REPORT)
        self.assertEqual(decide_targets(REPORT, bp, "word")[0], ["word"])
        self.assertEqual(decide_targets(REPORT, bp, "all")[0], ["word", "excel", "ppt"])

    def test_auto_picks_excel_for_data(self):
        raw = "a,b\n1,2\n3,4\n"
        targets, _ = decide_targets(raw, parse(raw), "auto")
        self.assertIn("excel", targets)

    def test_auto_picks_ppt_for_deck_words(self):
        raw = "Board deck\n\nGrowth\n- up 10%\n- margin steady\n"
        targets, _ = decide_targets(raw, parse(raw), "auto")
        self.assertIn("ppt", targets)

    def test_auto_falls_back_to_word(self):
        raw = "Short note about the meeting"
        self.assertEqual(decide_targets(raw, parse(raw), "auto")[0], ["word"])

    def test_slug(self):
        self.assertEqual(slug("Q3 Site Progress Report!"), "q3-site-progress-report")
        self.assertEqual(slug(""), "document")


class TestLLMLayer(unittest.TestCase):
    def test_offline_returns_blueprint_untouched(self):
        bp = parse(REPORT)
        out, status = llm.enhance(bp, REPORT, api_key="", base="https://api.deepseek.com/v1")
        self.assertIs(out, bp)
        self.assertIn("offline", status)

    def test_merge_never_drops_tables_or_facts(self):
        bp = parse(REPORT)
        merged = llm._merge(bp, {
            "title": "Polished Title",
            "summary": ["one clean point"],
            "sections": [{"heading": "Manpower", "level": 1, "bullets": ["headcount up 12%"],
                          "notes": "say this"}],
            "next_steps": ["decide by Friday"],
        })
        self.assertEqual(merged.title, "Polished Title")
        self.assertEqual(len(merged.all_tables), len(bp.all_tables))
        self.assertEqual(merged.all_tables[0].rows, bp.all_tables[0].rows)
        self.assertEqual(merged.facts, bp.facts)
        self.assertEqual(merged.sections[0].notes, "say this")

    def test_merge_keeps_sections_the_model_dropped(self):
        bp = parse(REPORT)
        merged = llm._merge(bp, {"sections": [{"heading": "Manpower", "bullets": ["x"]}]})
        headings = [s.heading.lower() for s in merged.sections]
        self.assertIn("risks", headings)

    def test_extract_json_handles_fences(self):
        self.assertEqual(llm._extract_json('```json\n{"a": 1}\n```'), {"a": 1})
        self.assertIsNone(llm._extract_json("no json here"))

    def test_local_endpoint_needs_no_key(self):
        self.assertTrue(llm.available({"key": "", "base": "http://localhost:11434/v1",
                                       "model": "x"}))


class TestEndToEnd(unittest.TestCase):
    def test_generate_all_three_and_verify(self):
        with tempfile.TemporaryDirectory() as d:
            result = generate(REPORT, out_dir=d, targets="all", quiet=True)
            self.assertEqual(set(result["files"]), {"word", "excel", "ppt"})
            for path in result["files"].values():
                self.assertTrue(path.exists())
                self.assertGreater(path.stat().st_size, 5000)
            self.assertEqual(result["status"], "ok", verify.format_report(result["checks"]))

    def test_generate_survives_messy_input(self):
        messy = "\n\n   \n#### \nfoo:::bar\n|||\n\t\t\n123\n"
        with tempfile.TemporaryDirectory() as d:
            result = generate(messy, out_dir=d, targets="word", quiet=True)
            self.assertTrue(result["files"]["word"].exists())

    def test_unicode_input(self):
        raw = "تقرير المشروع\n\nالمنطقة, العدد\nالشمال, 120\nالجنوب, 80\n"
        with tempfile.TemporaryDirectory() as d:
            result = generate(raw, out_dir=d, targets="all", quiet=True)
            self.assertEqual(result["status"], "ok")


if __name__ == "__main__":
    unittest.main(verbosity=2)
