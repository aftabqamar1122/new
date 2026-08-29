"""OfficeMind CLI — raw text in, finished Office files out."""

from __future__ import annotations

import argparse
import re
import sys
from datetime import date
from pathlib import Path

from . import build_excel, build_ppt, build_word, export, llm, verify as verify_mod
from .model import Blueprint
from .parse import parse

DECK_WORDS = ("deck", "slide", "slides", "presentation", "powerpoint", "ppt", "pitch")
SHEET_WORDS = ("excel", "workbook", "spreadsheet", "sheet", "xlsx", "budget", "tracker")
DOC_WORDS = ("report", "document", "word", "docx", "memo", "letter", "proposal", "minutes")


def slug(text: str, fallback: str = "document") -> str:
    s = re.sub(r"[^A-Za-z0-9]+", "-", (text or "").strip()).strip("-").lower()
    return (s or fallback)[:60]


def decide_targets(raw: str, bp: Blueprint, requested: str) -> tuple[list[str], str]:
    """Return (targets, reason). 'auto' picks what the input actually calls for."""
    if requested and requested != "auto":
        if requested == "all":
            return ["word", "excel", "ppt"], "requested: all three"
        return [requested], f"requested: {requested}"

    low = raw.lower()[:4000]
    targets: list[str] = []
    reasons: list[str] = []

    if bp.has_data:
        targets.append("excel")
        reasons.append(f"{len(bp.all_tables)} data table(s) found")
    if any(w in low for w in DECK_WORDS):
        targets.append("ppt")
        reasons.append("deck keywords in the input")
    if bp.sections and (bp.word_count > 40 or any(w in low for w in DOC_WORDS)):
        targets.append("word")
        reasons.append("narrative sections found")

    if not targets:
        targets = ["word"]
        reasons.append("short prose input")
    if "excel" in targets and "word" not in targets and any(w in low for w in DOC_WORDS):
        targets.append("word")
    return targets, "; ".join(reasons)


def generate(raw: str, out_dir: str | Path = "output", targets: str = "auto",
             title: str = "", author: str = "", theme: str = "slate",
             name: str = "", use_llm: bool | None = None, api_key: str | None = None,
             model: str | None = None, base: str | None = None,
             source: str = "raw input", quiet: bool = False,
             verify: bool = True, pdf: bool = False) -> dict:
    """Parse raw text and write the requested Office files. Returns a result dict."""
    bp = parse(raw, title=title, author=author, source=source)

    status = "offline (deterministic parse)"
    want_llm = llm.available(llm.config(api_key, base, model)) if use_llm is None else use_llm
    if want_llm:
        bp, status = llm.enhance(bp, raw, api_key=api_key, model=model, base=base)

    chosen, reason = decide_targets(raw, bp, targets)
    stem = slug(name or bp.title) + "_" + date.today().strftime("%Y-%m-%d")
    out = Path(out_dir)
    written: dict[str, Path] = {}

    if "word" in chosen:
        written["word"] = build_word.build(bp, out / f"{stem}.docx", theme)
    if "excel" in chosen:
        written["excel"] = build_excel.build(bp, out / f"{stem}.xlsx", theme)
    if "ppt" in chosen:
        written["ppt"] = build_ppt.build(bp, out / f"{stem}.pptx", theme)

    checks = verify_mod.verify(written) if verify else {}
    pdfs: dict[str, Path] = {}
    pdf_notes: list[str] = []
    if pdf:
        for kind, path in written.items():
            made, msg = export.to_pdf(path)
            if made:
                pdfs[kind] = made
            else:
                pdf_notes.append(f"{kind}: {msg}")

    result = {"blueprint": bp, "files": written, "llm": status, "reason": reason,
              "checks": checks, "status": verify_mod.worst(checks) if checks else "unchecked",
              "pdfs": pdfs, "pdf_notes": pdf_notes}
    if not quiet:
        _report(result)
    return result


def _report(result: dict) -> None:
    bp: Blueprint = result["blueprint"]
    print(f"\n  {bp.title}")
    print(f"  {len(bp.sections)} sections · {len(bp.all_tables)} tables · "
          f"{len(bp.summary)} summary points · {bp.word_count} words")
    print(f"  content: {result['llm']}")
    print(f"  chose: {result['reason']}\n")
    for kind, path in result["files"].items():
        size = path.stat().st_size / 1024
        print(f"  {kind:6s} {path}  ({size:,.0f} KB)")
    for kind, path in result.get("pdfs", {}).items():
        print(f"  pdf    {path}")
    for note in result.get("pdf_notes", []):
        print(f"  pdf    {note}")
    if result.get("checks"):
        print("\n  verification")
        print(verify_mod.format_report(result["checks"]))
        summary = {"ok": "all checks passed",
                   "warn": "passed with warnings — see above",
                   "fail": "FAILED — do not ship these files as they are"}
        print(f"\n  {summary[result['status']]}")
    print()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="officemind",
        description="Give it raw notes; it builds the Word, Excel and PowerPoint files.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""examples:
  officemind "Q3 report ..."                 # auto-detect what to build
  officemind -f notes.txt -t all             # all three files
  officemind -f data.csv -t excel            # workbook with analysis + checks
  cat notes.md | officemind -f - -t ppt      # deck from stdin
  officemind -f notes.txt --llm              # polish wording with DeepSeek""")
    ap.add_argument("text", nargs="?", default="", help="raw text (or use -f)")
    ap.add_argument("-f", "--file", help="input file; '-' reads stdin")
    ap.add_argument("-o", "--out", default="output", help="output directory (default: output)")
    ap.add_argument("-t", "--type", default="auto",
                    choices=["auto", "word", "excel", "ppt", "all"], help="what to build")
    ap.add_argument("--title", default="", help="override the detected title")
    ap.add_argument("--author", default="", help="author name for file properties")
    ap.add_argument("--theme", default="slate",
                    choices=["slate", "graphite", "sand", "forest"], help="visual theme")
    ap.add_argument("--name", default="", help="output filename stem")
    ap.add_argument("--llm", dest="llm", action="store_true", help="force LLM polish on")
    ap.add_argument("--no-llm", dest="llm", action="store_false", help="force LLM polish off")
    ap.set_defaults(llm=None)
    ap.add_argument("--api-key", default=None, help="DeepSeek/OpenAI-compatible key")
    ap.add_argument("--model", default=None, help="model id (default: deepseek-chat)")
    ap.add_argument("--base", default=None, help="API base url (e.g. http://localhost:11434/v1)")
    ap.add_argument("--json", dest="dump_json", metavar="PATH", default=None,
                    help="also write the parsed blueprint as JSON")
    ap.add_argument("--pdf", action="store_true",
                    help="also export PDFs (needs a working LibreOffice)")
    ap.add_argument("--no-verify", dest="verify", action="store_false",
                    help="skip the post-build QA pass")
    ap.set_defaults(verify=True)
    ap.add_argument("-q", "--quiet", action="store_true")
    args = ap.parse_args(argv)

    source = "raw input"
    if args.file == "-":
        raw = sys.stdin.read()
        source = "stdin"
    elif args.file:
        path = Path(args.file)
        if not path.exists():
            print(f"error: no such file: {path}", file=sys.stderr)
            return 2
        raw = path.read_text(encoding="utf-8", errors="replace")
        source = path.name
    elif args.text:
        raw = args.text
    elif not sys.stdin.isatty():
        raw = sys.stdin.read()
        source = "stdin"
    else:
        print("Paste your raw notes, then press Ctrl-D:\n")
        raw = sys.stdin.read()
        source = "pasted notes"

    if not raw.strip():
        print("error: no input text", file=sys.stderr)
        return 2

    result = generate(raw, out_dir=args.out, targets=args.type, title=args.title,
                      author=args.author, theme=args.theme, name=args.name,
                      use_llm=args.llm, api_key=args.api_key, model=args.model,
                      base=args.base, source=source, quiet=args.quiet,
                      verify=args.verify, pdf=args.pdf)

    if args.dump_json:
        Path(args.dump_json).write_text(result["blueprint"].to_json(), encoding="utf-8")
        if not args.quiet:
            print(f"  json   {args.dump_json}\n")
    return 1 if result.get("status") == "fail" else 0


if __name__ == "__main__":
    raise SystemExit(main())
