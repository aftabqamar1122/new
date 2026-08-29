"""OfficeMind — raw notes in, finished Word / Excel / PowerPoint files out.

    from office_agent import generate
    generate("Q3 report ...", out_dir="output", targets="all")

Works with no API key at all. Set DEEPSEEK_API_KEY (or point
OFFICEMIND_LLM_BASE at a local Ollama) to add optional wording polish.
"""

from .cli import generate, main            # noqa: F401
from .model import Blueprint, Section, Table   # noqa: F401
from .parse import parse                   # noqa: F401

__version__ = "1.0.0"
__all__ = ["generate", "main", "parse", "Blueprint", "Section", "Table"]
