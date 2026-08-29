"""Blueprint — the neutral document model every builder reads from.

Raw text is parsed into a Blueprint once; Word, Excel and PowerPoint builders
then render the same Blueprint. Tables always carry parsed data, never prose,
so no builder (and no LLM) can restate a number differently.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from datetime import date
from typing import Any


@dataclass
class Table:
    """A rectangular dataset lifted out of the raw input."""

    name: str = "Data"
    headers: list[str] = field(default_factory=list)
    rows: list[list[Any]] = field(default_factory=list)
    caption: str = ""

    @property
    def n_rows(self) -> int:
        return len(self.rows)

    @property
    def n_cols(self) -> int:
        return len(self.headers) or (len(self.rows[0]) if self.rows else 0)

    def column(self, index: int) -> list[Any]:
        return [r[index] if index < len(r) else None for r in self.rows]


@dataclass
class Section:
    """One heading plus everything that belongs under it."""

    heading: str = ""
    level: int = 1
    paragraphs: list[str] = field(default_factory=list)
    bullets: list[str] = field(default_factory=list)
    tables: list[Table] = field(default_factory=list)
    notes: str = ""

    @property
    def is_empty(self) -> bool:
        return not (self.paragraphs or self.bullets or self.tables)


@dataclass
class Blueprint:
    title: str = "Untitled"
    subtitle: str = ""
    author: str = ""
    date: str = field(default_factory=lambda: date.today().strftime("%d %b %Y"))
    summary: list[str] = field(default_factory=list)
    sections: list[Section] = field(default_factory=list)
    tables: list[Table] = field(default_factory=list)
    facts: dict[str, str] = field(default_factory=dict)
    next_steps: list[str] = field(default_factory=list)
    source: str = "raw input"

    # ---- serialization -------------------------------------------------
    def to_dict(self) -> dict:
        return asdict(self)

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, default=str)

    @classmethod
    def from_dict(cls, data: dict) -> "Blueprint":
        def _table(t: dict) -> Table:
            return Table(
                name=str(t.get("name") or "Data"),
                headers=[str(h) for h in t.get("headers") or []],
                rows=[list(r) for r in t.get("rows") or []],
                caption=str(t.get("caption") or ""),
            )

        sections = []
        for s in data.get("sections") or []:
            sections.append(
                Section(
                    heading=str(s.get("heading") or ""),
                    level=int(s.get("level") or 1),
                    paragraphs=[str(p) for p in s.get("paragraphs") or []],
                    bullets=[str(b) for b in s.get("bullets") or []],
                    tables=[_table(t) for t in s.get("tables") or []],
                    notes=str(s.get("notes") or ""),
                )
            )
        bp = cls(
            title=str(data.get("title") or "Untitled"),
            subtitle=str(data.get("subtitle") or ""),
            author=str(data.get("author") or ""),
            summary=[str(x) for x in data.get("summary") or []],
            sections=sections,
            tables=[_table(t) for t in data.get("tables") or []],
            facts={str(k): str(v) for k, v in (data.get("facts") or {}).items()},
            next_steps=[str(x) for x in data.get("next_steps") or []],
            source=str(data.get("source") or "raw input"),
        )
        if data.get("date"):
            bp.date = str(data["date"])
        return bp

    # ---- convenience ---------------------------------------------------
    @property
    def all_tables(self) -> list[Table]:
        out = list(self.tables)
        for s in self.sections:
            out.extend(s.tables)
        return out

    @property
    def has_data(self) -> bool:
        return any(t.n_rows >= 2 for t in self.all_tables)

    @property
    def word_count(self) -> int:
        n = len(self.summary) + len(self.next_steps)
        for s in self.sections:
            n += len(" ".join(s.paragraphs).split()) + len(s.bullets)
        return n
