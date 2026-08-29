"""Best-effort PDF export via a local LibreOffice, when one is installed.

Optional and non-fatal: if soffice is missing or fails, the caller is told and
the Office files are still delivered.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path


def soffice() -> str | None:
    for name in ("soffice", "libreoffice"):
        found = shutil.which(name)
        if found:
            return found
    return None


def to_pdf(path: str | Path, timeout: int = 240) -> tuple[Path | None, str]:
    """Convert one Office file to PDF. Returns (pdf_path_or_None, message)."""
    exe = soffice()
    src = Path(path)
    if not exe:
        return None, "LibreOffice not installed — skipped PDF export"
    if not src.exists():
        return None, f"missing source file: {src}"

    with tempfile.TemporaryDirectory() as profile:
        cmd = [exe, "--headless", "--norestore",
               f"-env:UserInstallation=file://{profile}/lo",
               "--convert-to", "pdf", "--outdir", str(src.parent), str(src)]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                                  env={**os.environ, "HOME": profile})
        except subprocess.TimeoutExpired:
            return None, f"PDF export timed out after {timeout}s"
        except OSError as e:
            return None, f"PDF export failed to start: {e}"

    pdf = src.with_suffix(".pdf")
    if pdf.exists():
        return pdf, "ok"
    detail = (proc.stderr or proc.stdout or "").strip().splitlines()
    return None, f"LibreOffice could not convert the file: {detail[-1] if detail else 'no output'}"
