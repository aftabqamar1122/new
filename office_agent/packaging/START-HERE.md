# OfficeMind — start here

Raw notes in, finished **Word + Excel + PowerPoint** files out.
No API key. No Microsoft Office needed. Nothing leaves your computer.

---

## 1. Install Python (once)

- **Windows:** get Python 3.10+ from <https://python.org/downloads> and tick
  **“Add Python to PATH”** during setup.
- **macOS:** `brew install python3`, or download from python.org.
- **Linux:** `sudo apt install python3 python3-venv python3-pip`

Check it worked — open a terminal (Windows: press Start, type `cmd`, Enter):

```
python --version
```

## 2. Run it

Unzip this folder anywhere, then:

**Windows** — double-click **`run.bat`**.
The first run creates a local environment and installs three libraries (about
30 seconds). After that it starts instantly. Paste your notes, press
**Ctrl-Z then Enter**, and your files appear in the `output` folder.

**macOS / Linux** — in a terminal:

```bash
cd officemind
./run.sh
```

Paste your notes, press **Ctrl-D**, and the files land in `output/`.

That is the whole setup. Everything below is optional.

---

## 3. Try it on the sample

```bash
./run.sh -f office_agent/samples/site_report.txt -t all      # macOS / Linux
run.bat -f office_agent\samples\site_report.txt -t all       # Windows
```

You get three files in `output/` and a verification report in the terminal:

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

---

## 4. How to write your notes

Just type the way you normally would. The parser understands:

```
Q3 Site Progress Report            <- first line becomes the title
Project: Almeria Tower             <- key: value becomes cover facts
Prepared by: A. Qamar
Date: 15-Aug-2026

EXECUTIVE SUMMARY                  <- ALL CAPS, "1. Heading" and "Heading:" are headings
- Concrete works are 12% ahead     <- "-", "*", "•" and "1." are bullets
- Manpower cost is 8% over budget

1. Manpower
Average headcount rose from 240 to 268.     <- plain lines become paragraphs

Region, Planned, Actual, Cost      <- CSV, TAB, | pipe | or aligned columns
North, 120, 138, 412000               become real Excel data with real number types
South, 60, 55, 168500
East, 60, 75, 244300

Next Steps                         <- becomes the numbered closing section / slide
- Confirm rebar PO by 5 Sep
```

`$1,234.50`, `SAR 900`, `12%`, `(2,500)` and a dozen date formats are converted
to genuine Excel numbers and dates — not text that merely looks numeric.

## 5. Everyday commands

Replace `./run.sh` with `run.bat` on Windows.

```bash
./run.sh -f notes.txt                    # auto: picks what the notes call for
./run.sh -f notes.txt -t all             # force all three files
./run.sh -f data.csv  -t excel           # workbook + analysis + checks
./run.sh -f notes.txt -t ppt             # deck only
./run.sh -f notes.txt -o "C:\Reports"    # choose the output folder
./run.sh -f notes.txt --theme forest     # slate | graphite | sand | forest
./run.sh -f notes.txt --title "Q3 Report" --author "A. Qamar"
./run.sh -f notes.txt --pdf              # also PDFs (needs LibreOffice installed)
```

## 6. What you get

**Word** — real heading styles, cover facts block, live table of contents
(right-click → Update Field), captioned tables with repeating header rows,
`Page X of Y` footer built from real Word fields.

**Excel** — Cover sheet with clickable contents; each dataset as a real Excel
Table with proper number formats and frozen headers; an **Analysis** sheet built
from live `SUMIF` formulas with a total row, `% of total` data bars and a bar
chart; and a **Checks** sheet that ties every analysis total back to the source
data. Change a number in the data and everything recalculates.

**PowerPoint** — 16:9 deck on master layouts: title, executive summary, agenda,
one slide per section (six bullets max), a chart slide whose title states the
finding, a data table, next steps, and speaker notes on every single slide.

---

## 7. Optional: sharper wording with DeepSeek

Everything above works with no key. If you want the agent to rewrite headings,
bullets and speaker notes into tighter prose, add a key:

**Windows (cmd):**
```
set DEEPSEEK_API_KEY=sk-your-key-here
run.bat -f notes.txt -t all --llm
```

**macOS / Linux:**
```bash
export DEEPSEEK_API_KEY=sk-your-key-here
./run.sh -f notes.txt -t all --llm
```

Get a key at <https://platform.deepseek.com>. A typical report costs well under
a cent.

Prefer a fully local model? Install [Ollama](https://ollama.com), then:

```bash
export OFFICEMIND_LLM_BASE=http://localhost:11434/v1
export OFFICEMIND_MODEL=qwen2.5:7b
./run.sh -f notes.txt --llm
```

Two rules hold either way: **your data tables are never sent to any model** —
they are parsed locally and merged back untouched, so no figure can be invented
— and if the model call fails for any reason, the run falls back to the offline
parse and tells you so.

---

## 8. If something goes wrong

| Problem | Fix |
|---|---|
| `python is not recognised` | Reinstall Python with **Add Python to PATH** ticked |
| `run.bat` flashes and closes | Open `cmd`, `cd` to the folder, run `run.bat` to see the error |
| No output files | Check the terminal — the run prints the exact paths it wrote |
| Table not detected | Keep one row per line and a consistent separator (comma, tab or `\|`) |
| Wrong title | Pass `--title "Your Title"` |
| `--pdf` does nothing | Install LibreOffice; PDF export needs it |

Run the test suite any time to confirm the install is healthy:

```bash
python -m unittest discover -s tests -v      # 41 tests, ~1 second
```

Full reference: `office_agent/README.md`.
The chat-agent version of this same system: `office_agent/SYSTEM_PROMPT.md`.
