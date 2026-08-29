"""Rule-based parser: raw text -> Blueprint. Runs entirely offline, no API key.

The parser recognises, in order:
  1. delimited data blocks (tab / pipe / CSV / aligned columns) -> tables
  2. headings (markdown #, ALL CAPS, trailing colon, numbered section titles)
  3. bullets (-, *, o, numbers) and "key: value" fact lines
  4. everything else -> paragraphs under the current heading
"""

from __future__ import annotations

import re
from datetime import datetime, date
from typing import Any

from .model import Blueprint, Section, Table

BULLET_RE = re.compile(r"^\s*(?:[-*•‣●◦o–—]|\(?\d{1,2}[.)])\s+(?P<text>.+)$")
NUM_HEAD_RE = re.compile(r"^\s*(\d{1,2}(?:\.\d{1,2})*)[.)]?\s+(?P<text>[A-Z][^.!?]{2,70})\s*:?\s*$")
MD_HEAD_RE = re.compile(r"^\s*(?P<hashes>#{1,6})\s+(?P<text>.+?)\s*#*\s*$")
KV_RE = re.compile(r"^\s*(?P<key>[A-Za-z][A-Za-z0-9 /&._'()-]{1,38})\s*[:=]\s*(?P<val>.+?)\s*$")
CURRENCY_RE = re.compile(r"^\s*(?P<sym>[$€£¥₹﷼]|SAR|AED|USD|EUR|GBP|PKR|INR)?\s*"
                         r"(?P<num>-?\(?\d[\d,\s]*\.?\d*\)?)\s*(?P<sym2>[$€£¥₹]|SAR|AED|USD|EUR|GBP|PKR|INR)?\s*$",
                         re.IGNORECASE)
PERCENT_RE = re.compile(r"^\s*-?\d+(?:\.\d+)?\s*%\s*$")

DATE_FORMATS = (
    "%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%d-%m-%Y", "%d.%m.%Y", "%d-%b-%Y",
    "%d %b %Y", "%d %B %Y", "%b %d, %Y", "%B %d, %Y", "%Y/%m/%d", "%d-%b-%y",
)

ACTION_WORDS = ("next step", "action item", "action point", "to do", "todo",
                "way forward", "recommendation", "follow up", "follow-up")
SUMMARY_WORDS = ("summary", "overview", "executive summary", "highlights", "key points",
                 "abstract", "at a glance")


# --------------------------------------------------------------------------
# value typing
# --------------------------------------------------------------------------
def coerce(raw: Any) -> Any:
    """Turn a raw cell string into int / float / date / str."""
    if raw is None:
        return None
    if isinstance(raw, (int, float, date, datetime)):
        return raw
    s = str(raw).strip()
    if not s or s in {"-", "--", "n/a", "N/A", "NA", "null", "None"}:
        return None

    if PERCENT_RE.match(s):
        try:
            return float(s.replace("%", "").strip()) / 100.0
        except ValueError:
            return s

    m = CURRENCY_RE.match(s)
    if m and m.group("num"):
        num = m.group("num").replace(",", "").replace(" ", "")
        neg = num.startswith("(") and num.endswith(")")
        num = num.strip("()")
        try:
            val = float(num)
            if neg:
                val = -val
            return int(val) if val.is_integer() and "." not in num else val
        except ValueError:
            pass

    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return s


def cell_kind(value: Any, raw: str = "") -> str:
    if value is None:
        return "blank"
    if isinstance(value, (date, datetime)):
        return "date"
    if isinstance(value, bool):
        return "text"
    if isinstance(value, (int, float)):
        if PERCENT_RE.match(raw.strip()):
            return "percent"
        if CURRENCY_RE.match(raw.strip()) and (CURRENCY_RE.match(raw.strip()).group("sym")
                                               or CURRENCY_RE.match(raw.strip()).group("sym2")):
            return "currency"
        return "number"
    return "text"


def column_kind(values: list[Any], raws: list[str]) -> str:
    kinds = [cell_kind(v, r) for v, r in zip(values, raws) if v is not None]
    if not kinds:
        return "text"
    for k in ("currency", "percent", "date"):
        if kinds.count(k) >= max(1, int(len(kinds) * 0.6)):
            return k
    if all(k in ("number", "currency", "percent") for k in kinds):
        return "number"
    return "text"


# --------------------------------------------------------------------------
# table extraction
# --------------------------------------------------------------------------
def _split(line: str, delim: str) -> list[str]:
    if delim == "|":
        parts = line.strip().strip("|").split("|")
    elif delim == "\t":
        parts = line.split("\t")
    elif delim == ",":
        parts = _split_csv(line)
    else:  # aligned columns
        parts = re.split(r"\s{2,}", line.strip())
    return [p.strip() for p in parts]


def _split_csv(line: str) -> list[str]:
    out, cur, quoted = [], "", False
    for ch in line:
        if ch == '"':
            quoted = not quoted
        elif ch == "," and not quoted:
            out.append(cur)
            cur = ""
        else:
            cur += ch
    out.append(cur)
    return out


def _is_md_rule(line: str) -> bool:
    return bool(re.fullmatch(r"[\s|:+-]{3,}", line.strip())) and "-" in line


def _field_count(line: str, delim: str) -> int:
    if _is_md_rule(line):
        return -1
    parts = [p for p in _split(line, delim)]
    return len(parts) if len([p for p in parts if p]) >= 2 else 0


def _detect_blocks(lines: list[str]) -> list[tuple[int, int, str]]:
    """Return (start, end_exclusive, delimiter) for each delimited run of lines."""
    blocks: list[tuple[int, int, str]] = []
    i = 0
    while i < len(lines):
        if not lines[i].strip():
            i += 1
            continue
        best = None
        for delim in ("\t", "|", ",", "  "):
            n = _field_count(lines[i], delim)
            if n < 2:
                continue
            j = i + 1
            while j < len(lines) and lines[j].strip():
                cnt = _field_count(lines[j], delim)
                if cnt == -1:          # markdown separator row, keep going
                    j += 1
                    continue
                if abs(cnt - n) > 0:
                    break
                j += 1
            rows = j - i
            if rows >= 2 and (best is None or rows > best[0] or (rows == best[0] and n > best[2])):
                best = (rows, delim, n)
        if best and best[0] >= 2:
            blocks.append((i, i + best[0], best[1]))
            i += best[0]
        else:
            i += 1
    return blocks


def _build_table(lines: list[str], delim: str, name: str) -> Table | None:
    grid = [_split(ln, delim) for ln in lines if not _is_md_rule(ln)]
    grid = [row for row in grid if any(c.strip() for c in row)]
    if len(grid) < 2:
        return None
    width = max(len(r) for r in grid)
    grid = [r + [""] * (width - len(r)) for r in grid]

    first, rest = grid[0], grid[1:]
    first_numeric = sum(1 for c in first if isinstance(coerce(c), (int, float)))
    rest_numeric = sum(1 for r in rest for c in r if isinstance(coerce(c), (int, float)))
    has_header = first_numeric <= width // 3 and (rest_numeric > 0 or all(c.strip() for c in first))

    if has_header:
        headers = [c.strip() or f"Column {i+1}" for i, c in enumerate(first)]
        data_rows = rest
    else:
        headers = [f"Column {i+1}" for i in range(width)]
        data_rows = grid

    rows = [[coerce(c) for c in r] for r in data_rows]
    rows = [r for r in rows if any(c is not None and str(c).strip() for c in r)]
    if not rows:
        return None
    return Table(name=name, headers=headers, rows=rows)


# --------------------------------------------------------------------------
# main parse
# --------------------------------------------------------------------------
def _clean_heading(text: str) -> str:
    text = text.strip().strip(":").strip()
    text = re.sub(r"^\d{1,2}(?:\.\d{1,2})*[.)]?\s+", "", text)
    if text.isupper() and len(text) > 3:
        text = text.title()
    return text.strip()


def _looks_like_label(text: str) -> bool:
    """A short caption-ish line: no terminal punctuation, few words."""
    t = text.strip()
    if not t or len(t) > 60 or len(t.split()) > 8:
        return False
    if t[-1] in ".!?;,":
        return False
    return t[0].isupper() or t[0].isdigit()


def _title_case_ratio(text: str) -> float:
    words = [w for w in re.findall(r"[A-Za-z][A-Za-z'-]*", text)]
    if not words:
        return 0.0
    return sum(1 for w in words if w[0].isupper()) / len(words)


def _heading_level(line: str, next_line: str = "") -> int | None:
    m = MD_HEAD_RE.match(line)
    if m:
        return min(len(m.group("hashes")), 4)
    stripped = line.strip()
    if BULLET_RE.match(line) and not NUM_HEAD_RE.match(line):
        return None
    if NUM_HEAD_RE.match(line):
        depth = NUM_HEAD_RE.match(line).group(1).count(".") + 1
        return min(depth, 3)
    if len(stripped) <= 70 and stripped.isupper() and re.search(r"[A-Z]{3}", stripped):
        return 1
    if (stripped.endswith(":") and len(stripped) <= 70 and not KV_RE.match(stripped)
            and len(stripped.split()) <= 9):
        return 2
    # soft heading: a short label-like line introducing bullets or a table
    if _looks_like_label(stripped) and not KV_RE.match(stripped):
        if _title_case_ratio(stripped) >= 0.6 or stripped.lower().rstrip("s") in (
                "next step", "risk", "issue", "finding", "recommendation",
                "assumption", "scope", "background", "conclusion", "detail"):
            if BULLET_RE.match(next_line) or not next_line:
                return 2
    return None


def parse(raw: str, title: str = "", author: str = "", source: str = "raw input") -> Blueprint:
    """Parse raw text into a Blueprint. Never raises on odd input."""
    raw = (raw or "").replace("\r\n", "\n").replace("\r", "\n")
    lines = raw.split("\n")

    # 1. pull out data blocks first so their commas/pipes never look like prose
    tables: dict[int, Table] = {}
    consumed: set[int] = set()
    for start, end, delim in _detect_blocks(lines):
        label = ""
        for k in range(start - 1, max(-1, start - 3), -1):
            if k >= 0 and lines[k].strip():
                cand = lines[k].strip()
                if (_looks_like_label(cand) or MD_HEAD_RE.match(cand)) and not KV_RE.match(cand):
                    label = _clean_heading(cand)
                break
        tbl = _build_table(lines[start:end], delim, label or f"Table {len(tables)+1}")
        if tbl and tbl.n_rows >= 1 and tbl.n_cols >= 2:
            tables[start] = tbl
            consumed.update(range(start, end))

    bp = Blueprint(author=author, source=source)
    current = Section(heading="Overview", level=1)
    sections: list[Section] = []
    pending: list[str] = []
    title_found = bool(title)
    if title:
        bp.title = title

    def flush_paragraph() -> None:
        if pending:
            text = " ".join(p.strip() for p in pending).strip()
            if text:
                current.paragraphs.append(text)
            pending.clear()

    def push_section() -> None:
        flush_paragraph()
        if not current.is_empty or current.heading not in ("Overview", ""):
            sections.append(current)

    for idx, line in enumerate(lines):
        if idx in consumed:
            if idx in tables:
                flush_paragraph()
                current.tables.append(tables[idx])
            continue

        stripped = line.strip()
        if not stripped:
            flush_paragraph()
            continue

        # title: first meaningful short line before any content
        if not title_found and not sections and current.is_empty and not pending:
            cand = MD_HEAD_RE.match(line)
            text = cand.group("text").strip() if cand else stripped
            if len(text) <= 90 and not BULLET_RE.match(line):
                kv = KV_RE.match(text)
                if kv and kv.group("key").strip().lower() in ("title", "subject", "topic"):
                    bp.title = kv.group("val").strip()
                else:
                    bp.title = _clean_heading(text)
                title_found = True
                continue

        nxt = ""
        for k in range(idx + 1, min(len(lines), idx + 4)):
            if k in consumed:
                break
            if lines[k].strip():
                nxt = lines[k]
                break
        level = _heading_level(line, nxt)
        if level is not None:
            m = MD_HEAD_RE.match(line)
            text = m.group("text") if m else stripped
            push_section()
            current = Section(heading=_clean_heading(text) or "Section", level=level)
            continue

        bm = BULLET_RE.match(line)
        if bm:
            flush_paragraph()
            current.bullets.append(bm.group("text").strip().rstrip(";"))
            continue

        kv = KV_RE.match(stripped)
        if kv and len(kv.group("val")) <= 80 and len(kv.group("key").split()) <= 5:
            key, val = kv.group("key").strip(), kv.group("val").strip()
            low = key.lower()
            if low in ("author", "prepared by", "by", "owner"):
                bp.author = bp.author or val
            elif low in ("date", "as of", "report date"):
                bp.date = val
            elif low in ("subtitle", "for", "client", "project"):
                bp.subtitle = bp.subtitle or (val if low != "project" else f"Project: {val}")
                bp.facts[key] = val
            else:
                bp.facts[key] = val
            continue

        pending.append(stripped)

    push_section()

    # tables that landed in the implicit Overview section float to the top level
    for sec in sections:
        if sec.heading == "Overview" and not sec.paragraphs and not sec.bullets and sec.tables:
            bp.tables.extend(sec.tables)
            sec.tables = []
    sections = [s for s in sections if not s.is_empty or s.heading not in ("Overview", "")]
    for sec in sections:                       # generic table names inherit their heading
        for t in sec.tables:
            if t.name.startswith("Table ") and sec.heading:
                t.name = sec.heading
    bp.sections = sections

    if bp.title == "Untitled" or not bp.title.strip():
        bp.title = _fallback_title(bp, source)
    _derive_summary(bp)
    _derive_next_steps(bp)
    if not bp.subtitle:
        bp.subtitle = f"Prepared {bp.date}"
    return bp


def _fallback_title(bp: Blueprint, source: str) -> str:
    """Pure-data input has no title line — build one from the file or the data."""
    stem = re.sub(r"\.[A-Za-z0-9]{1,5}$", "", source or "").strip()
    if stem and stem not in ("raw input", "stdin", "pasted notes", "-"):
        return re.sub(r"[_-]+", " ", stem).strip().title()
    tables = bp.all_tables
    if tables:
        t = tables[0]
        if not t.name.lower().startswith("table "):
            return f"{t.name} Summary"
        if t.headers:
            subject = " and ".join(h for h in t.headers[:2] if h)
            return f"{subject} Data".strip().title()
    if bp.sections and bp.sections[0].heading:
        return bp.sections[0].heading
    return "Untitled"


def _first_sentences(text: str, limit: int = 2) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+", text.strip())
    return [p.strip() for p in parts[:limit] if len(p.strip()) > 12]


def _derive_summary(bp: Blueprint) -> None:
    for sec in bp.sections:
        if any(w in sec.heading.lower() for w in SUMMARY_WORDS):
            bp.summary = sec.bullets[:6] or [s for p in sec.paragraphs for s in _first_sentences(p, 3)][:5]
            if bp.summary:
                return
    picked: list[str] = []
    for sec in bp.sections:
        if any(w in sec.heading.lower() for w in ACTION_WORDS):
            continue
        if sec.bullets:
            picked.append(f"{sec.heading}: {sec.bullets[0]}")
        elif sec.paragraphs:
            s = _first_sentences(sec.paragraphs[0], 1)
            if s:
                picked.append(f"{sec.heading}: {s[0]}")
        if len(picked) >= 5:
            break
    for t in bp.all_tables[:1]:
        picked.append(f"{t.name}: {t.n_rows} rows x {t.n_cols} columns of source data included.")
    bp.summary = picked[:6]


def _derive_next_steps(bp: Blueprint) -> None:
    for sec in bp.sections:
        if any(w in sec.heading.lower() for w in ACTION_WORDS):
            bp.next_steps = sec.bullets[:8] or [s for p in sec.paragraphs for s in _first_sentences(p, 2)][:6]
            if bp.next_steps:
                return
