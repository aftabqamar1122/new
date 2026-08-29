# OfficeMind

Give it raw notes. It gives you finished Word, Excel and PowerPoint files.

No API key. No cloud call. No Microsoft Office installation. The whole pipeline
is deterministic Python — an optional LLM layer only polishes wording, and it is
off unless you turn it on.

```bash
pip install python-docx openpyxl python-pptx

python -m office_agent -f office_agent/samples/site_report.txt -t all
```

```
  Q3 Site Progress Report
  4 sections · 1 tables · 3 summary points · 39 words
  content: offline (deterministic parse)
  chose: requested: all three

  word   output/q3-site-progress-report_2026-08-29.docx  (38 KB)
  excel  output/q3-site-progress-report_2026-08-29.xlsx  (11 KB)
  ppt    output/q3-site-progress-report_2026-08-29.pptx  (56 KB)

  verification
  word
    ✓ 6 real headings (levels [1, 2])
    ✓ table of contents is a live field (updates with F9)
    ✓ footer carries live page numbering (Page X of Y)
    ✓ 2 table(s), header rows set to repeat
  excel
    ✓ 4 sheets: Cover, Manpower, Analysis Manpower, Checks
    ✓ 27 live formulas (totals and shares recompute on edit)
    ✓ 3 tie-out check(s) wired to the source data
  ppt
    ✓ 8 slides at 13.33×7.50 in (16:9)
    ✓ every slide has speaker notes
    ✓ every slide has a title
    ✓ nothing sits off the canvas

  all checks passed
```

## What it accepts

Anything you would actually type or paste:

| In the raw text | What it becomes |
|---|---|
| First short line | Document title |
| `Project: X`, `Prepared by: Y`, `Date: Z` | Cover metadata |
| `# Heading`, `1. Heading`, `ALL CAPS`, `Heading:` | Real heading styles / slide titles |
| `-` `*` `•` `1.` lines | Bullets |
| CSV, TSV, `\| pipe \|` tables, aligned columns | Typed data tables |
| `EXECUTIVE SUMMARY` block | Executive summary in all three files |
| `Next Steps` block | Numbered next-steps section / closing slide |

Numbers, currency (`$1,234.50`, `SAR 900`), percentages (`12%`), negatives in
parentheses (`(2,500)`) and a dozen date formats are converted to real Excel
values — not text that looks like values.

## What it produces

**Word (.docx)** — styles-first document: Title/Heading 1–3/Body/Caption styles,
cover block with facts, a **live TOC field**, executive summary, body sections,
captioned tables with repeating header rows, and a `Page X of Y` footer built
from real Word fields.

**Excel (.xlsx)** — a workbook, not a data dump:
- `Cover` sheet with hyperlinked contents and key points
- one sheet per data table, written as a real Excel Table with per-column number
  formats, frozen header and sized columns
- an `Analysis` sheet that groups the first text column by every numeric column
  using **live `SUMIF` formulas**, a total row, a `% of total` column with data
  bars, and a bar chart
- a `Checks` sheet that ties every analysis total back to the source with
  `=IF(ABS(diff)<0.01,"OK","CHECK")` — edit the data and the checks still hold

**PowerPoint (.pptx)** — 16:9 deck on master layouts: title slide, executive
summary, agenda (when long enough), one content slide per section (bullets
chunked six to a slide), a native clustered-column chart whose title is an
assertion (`"North accounts for 50% of planned"`), a styled data table, next
steps, and **speaker notes on every slide**.

## Usage

```bash
python -m office_agent "raw text here"          # auto-detect what to build
python -m office_agent -f notes.txt -t all      # all three files
python -m office_agent -f data.csv -t excel     # workbook + analysis + checks
cat notes.md | python -m office_agent -t ppt    # deck from stdin
python -m office_agent                          # paste, then Ctrl-D
```

| Flag | What it does |
|---|---|
| `-f, --file` | Input file (`-` for stdin) |
| `-t, --type` | `auto` (default), `word`, `excel`, `ppt`, `all` |
| `-o, --out` | Output directory (default `output/`) |
| `--title` `--author` `--name` | Override the detected title / author / filename |
| `--theme` | `slate` (default), `graphite`, `sand`, `forest` |
| `--llm` / `--no-llm` | Force the optional wording polish on or off |
| `--api-key` `--model` `--base` | Point the LLM layer anywhere OpenAI-compatible |
| `--pdf` | Also export PDFs (needs a working LibreOffice) |
| `--json PATH` | Dump the parsed blueprint as JSON |
| `--no-verify` | Skip the post-build QA pass |

`auto` builds Excel when it finds data tables, PowerPoint when the text mentions
a deck or slides, and Word when there is narrative to write — it tells you which
rule fired.

From Python:

```python
from office_agent import generate

result = generate(open("notes.txt").read(), out_dir="output", targets="all")
print(result["files"]["excel"], result["status"])
```

## The optional LLM layer

Everything above runs with no key. Turn the polish layer on and the model
rewrites headings, bullets and speaker notes into cleaner prose:

```bash
export DEEPSEEK_API_KEY=sk-...
python -m office_agent -f notes.txt -t all --llm
```

Or point it at any OpenAI-compatible endpoint — including a local model, which
needs no key at all:

```bash
export OFFICEMIND_LLM_BASE=http://localhost:11434/v1   # Ollama
export OFFICEMIND_MODEL=qwen2.5:7b
python -m office_agent -f notes.txt --llm
```

Two guarantees hold whichever way you run it:

1. **Tables never reach the model.** Data is parsed locally and merged back
   verbatim, so no figure in any output can be invented or restated.
2. **Failure is never fatal.** A bad key, a timeout, a malformed reply — the run
   falls back to the deterministic parse and says so in the `content:` line.

## Verification

Every run reopens what it wrote and checks it (`--no-verify` to skip). The CLI
exits non-zero if any check fails, so it is safe in a script or a cron job.

## Tests

```bash
python3 -m unittest discover -s tests -v     # 41 tests
```

## Layout

```
office_agent/
├── model.py        Blueprint / Section / Table — the neutral document model
├── parse.py        raw text -> Blueprint (headings, bullets, tables, typing)
├── llm.py          optional OpenAI-compatible polish layer (DeepSeek by default)
├── theme.py        one visual identity shared by all three builders
├── build_word.py   Blueprint -> .docx
├── build_excel.py  Blueprint -> .xlsx
├── build_ppt.py    Blueprint -> .pptx
├── verify.py       post-build QA on the real files
├── export.py       best-effort PDF via LibreOffice
├── cli.py          argument parsing, target selection, reporting
└── SYSTEM_PROMPT.md  the agent prompt, if you would rather drive this by chat
```
