"""One shared visual identity for every file the agent produces."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Theme:
    name: str = "slate"
    # hex without '#', so openpyxl/python-docx/python-pptx can all use it
    ink: str = "1B2A33"          # near-black headings
    body: str = "33454F"         # body text
    muted: str = "6B7C86"        # captions, footers
    accent: str = "0F6E8C"       # primary accent (deep teal)
    accent_soft: str = "DCEBF0"  # accent tint for table headers / fills
    rule: str = "C9D6DC"         # hairlines and borders
    surface: str = "F4F7F8"      # zebra rows, cover panel
    paper: str = "FFFFFF"
    good: str = "1E7A4B"
    warn: str = "B26A00"
    bad: str = "B3261E"

    heading_font: str = "Calibri Light"
    body_font: str = "Calibri"
    mono_font: str = "Consolas"

    # chart series order
    @property
    def series(self) -> list[str]:
        return [self.accent, "8CBFCE", self.muted, "A7C9B4", "D8B98C", "9AA7B0"]


THEMES: dict[str, Theme] = {
    "slate": Theme(),
    "graphite": Theme(name="graphite", accent="3F4A54", accent_soft="E3E6E9",
                      rule="D2D6DA", surface="F5F6F7"),
    "sand": Theme(name="sand", ink="2A2622", body="4A423B", muted="857A6E",
                  accent="9A5B2E", accent_soft="F0E2D5", rule="DED2C4", surface="F8F4EF"),
    "forest": Theme(name="forest", ink="18251E", body="2F4438", muted="6E8275",
                    accent="1F6B4A", accent_soft="DCEBE2", rule="C6D8CD", surface="F2F7F4"),
}


def get_theme(name: str | None) -> Theme:
    return THEMES.get((name or "slate").lower(), THEMES["slate"])


def rgb(hex_str: str) -> tuple[int, int, int]:
    h = hex_str.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
