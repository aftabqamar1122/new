"""Optional LLM polish layer. The agent works fully without it.

Everything here is opt-in. With no key configured, `enhance()` returns the
blueprint untouched and the pipeline stays 100% offline and deterministic.

Any OpenAI-compatible endpoint works — DeepSeek by default, or a local
Ollama / LM Studio server, which needs no key at all:

    export DEEPSEEK_API_KEY=sk-...                         # DeepSeek
    export OFFICEMIND_LLM_BASE=http://localhost:11434/v1   # local Ollama
    export OFFICEMIND_MODEL=qwen2.5:7b

Hard rule enforced below: the model may rewrite prose, but it never touches
the parsed tables, so no figure in any output can be invented.
"""

from __future__ import annotations

import json
import os
import re
import ssl
import urllib.error
import urllib.request

from .model import Blueprint, Section

DEFAULT_BASE = "https://api.deepseek.com/v1"
DEFAULT_MODEL = "deepseek-chat"

SYSTEM = """You are a document-structuring engine for an offline Office generator.
You receive raw notes and a machine-parsed outline. You return ONLY JSON.

Rules:
- Never invent facts, numbers, dates, names or currency amounts. Use only what
  the raw notes contain. If something is unknown, leave it out.
- Do not return tables; numeric data is handled separately and must not be restated.
- Rewrite headings and bullets into clear, parallel, professional phrasing.
- Bullets: short phrases, no trailing full stops, max 18 words.
- `summary` is an executive summary: 3-5 bullets that carry the whole story.
- `notes` per section is what a presenter should say out loud (1-3 sentences).
- Keep the author's language (if the notes are in English, answer in English).

Return exactly this JSON shape and nothing else:
{"title": str, "subtitle": str, "summary": [str],
 "sections": [{"heading": str, "level": 1|2|3, "paragraphs": [str],
               "bullets": [str], "notes": str}],
 "next_steps": [str]}"""


def config(api_key: str | None = None, base: str | None = None,
           model: str | None = None) -> dict:
    return {
        "key": api_key or os.environ.get("DEEPSEEK_API_KEY")
               or os.environ.get("OFFICEMIND_API_KEY") or "",
        "base": (base or os.environ.get("OFFICEMIND_LLM_BASE") or DEFAULT_BASE).rstrip("/"),
        "model": model or os.environ.get("OFFICEMIND_MODEL") or DEFAULT_MODEL,
    }


def available(cfg: dict | None = None) -> bool:
    cfg = cfg or config()
    return bool(cfg["key"]) or "localhost" in cfg["base"] or "127.0.0.1" in cfg["base"]


def _post(cfg: dict, payload: dict, timeout: int = 90) -> dict:
    req = urllib.request.Request(
        f"{cfg['base']}/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {cfg['key'] or 'no-key'}"},
        method="POST",
    )
    ctx = ssl.create_default_context()
    ca = os.environ.get("REQUESTS_CA_BUNDLE") or os.environ.get("SSL_CERT_FILE")
    if ca and os.path.exists(ca):
        ctx.load_verify_locations(ca)
    with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _extract_json(text: str) -> dict | None:
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    if fence:
        text = fence.group(1)
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        return json.loads(text[start:end + 1])
    except json.JSONDecodeError:
        return None


def enhance(bp: Blueprint, raw: str, purpose: str = "report",
            api_key: str | None = None, base: str | None = None,
            model: str | None = None, max_chars: int = 12000) -> tuple[Blueprint, str]:
    """Return (blueprint, status). Falls back to the parsed blueprint on any failure."""
    cfg = config(api_key, base, model)
    if not available(cfg):
        return bp, "offline (no key configured — deterministic parse only)"

    outline = {
        "title": bp.title,
        "sections": [{"heading": s.heading, "level": s.level,
                      "bullets": s.bullets[:8], "paragraphs": s.paragraphs[:4]}
                     for s in bp.sections],
        "facts": bp.facts,
        "tables": [{"name": t.name, "headers": t.headers, "rows": t.n_rows}
                   for t in bp.all_tables],
    }
    user = (f"Deliverable: {purpose}\n\n"
            f"RAW NOTES\n---------\n{raw[:max_chars]}\n\n"
            f"MACHINE-PARSED OUTLINE\n----------------------\n"
            f"{json.dumps(outline, ensure_ascii=False, default=str)[:4000]}")

    payload = {
        "model": cfg["model"],
        "messages": [{"role": "system", "content": SYSTEM},
                     {"role": "user", "content": user}],
        "temperature": 0.2,
        "max_tokens": 3000,
        "response_format": {"type": "json_object"},
    }

    try:
        data = _post(cfg, payload)
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")[:200]
        if e.code in (400, 422) and "response_format" in body:
            payload.pop("response_format", None)
            try:
                data = _post(cfg, payload)
            except Exception as e2:                     # pragma: no cover
                return bp, f"LLM unavailable ({e2}) — used deterministic parse"
        else:
            return bp, f"LLM error {e.code}: {body} — used deterministic parse"
    except Exception as e:
        return bp, f"LLM unavailable ({e}) — used deterministic parse"

    try:
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError):
        return bp, "LLM returned an unexpected payload — used deterministic parse"

    parsed = _extract_json(content)
    if not parsed or not parsed.get("sections"):
        return bp, "LLM returned no usable structure — used deterministic parse"

    return _merge(bp, parsed), f"enhanced by {cfg['model']}"


def _merge(bp: Blueprint, data: dict) -> Blueprint:
    """Take prose from the model, keep every parsed table and fact intact."""
    merged = Blueprint(
        title=str(data.get("title") or bp.title),
        subtitle=str(data.get("subtitle") or bp.subtitle),
        author=bp.author,
        date=bp.date,
        summary=[str(x).strip() for x in (data.get("summary") or bp.summary) if str(x).strip()][:6],
        tables=list(bp.tables),
        facts=dict(bp.facts),
        next_steps=[str(x).strip() for x in (data.get("next_steps") or bp.next_steps)
                    if str(x).strip()][:8],
        source=bp.source,
    )

    leftovers = {i: s for i, s in enumerate(bp.sections)}
    new_sections: list[Section] = []
    for item in data.get("sections") or []:
        heading = str(item.get("heading") or "").strip()
        if not heading:
            continue
        sec = Section(
            heading=heading,
            level=int(item.get("level") or 1) if str(item.get("level", "1")).isdigit() else 1,
            paragraphs=[str(p).strip() for p in item.get("paragraphs") or [] if str(p).strip()],
            bullets=[str(b).strip() for b in item.get("bullets") or [] if str(b).strip()],
            notes=str(item.get("notes") or "").strip(),
        )
        match = None
        for i, old in leftovers.items():
            if old.heading and (old.heading.lower() in heading.lower()
                                or heading.lower() in old.heading.lower()):
                match = i
                break
        if match is not None:
            sec.tables = leftovers.pop(match).tables       # tables survive verbatim
        new_sections.append(sec)

    for _, orphan in sorted(leftovers.items()):            # nothing parsed is ever lost
        if orphan.tables:
            merged.tables.extend(orphan.tables)
        if orphan.bullets or orphan.paragraphs:
            if not any(s.heading.lower() == orphan.heading.lower() for s in new_sections):
                new_sections.append(orphan)

    merged.sections = new_sections or bp.sections
    return merged
