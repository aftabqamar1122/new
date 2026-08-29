#!/usr/bin/env bash
# OfficeMind launcher for macOS / Linux.  ./run.sh -f notes.txt -t all
set -euo pipefail
cd "$(dirname "$0")"

PY=${PYTHON:-python3}
if [ ! -d .venv ]; then
  echo "Creating a local Python environment..."
  "$PY" -m venv .venv
  # shellcheck disable=SC1091
  source .venv/bin/activate
  echo "Installing python-docx, openpyxl, python-pptx..."
  python -m pip install --quiet --upgrade pip
  python -m pip install --quiet -r requirements.txt
else
  # shellcheck disable=SC1091
  source .venv/bin/activate
fi

if [ $# -eq 0 ]; then
  echo
  echo "  OfficeMind — paste your raw notes below, then press Ctrl-D."
  echo
  python -m office_agent -t all
else
  python -m office_agent "$@"
fi
