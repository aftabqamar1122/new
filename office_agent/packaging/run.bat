@echo off
REM OfficeMind launcher for Windows. Double-click, or: run.bat -f notes.txt -t all
setlocal
cd /d "%~dp0"

where py >nul 2>nul && (set PY=py) || (set PY=python)

if not exist ".venv" (
  echo Creating a local Python environment...
  %PY% -m venv .venv || goto :nopython
  call .venv\Scripts\activate.bat
  echo Installing python-docx, openpyxl, python-pptx...
  python -m pip install --quiet --upgrade pip
  python -m pip install --quiet -r requirements.txt
) else (
  call .venv\Scripts\activate.bat
)

if "%~1"=="" (
  echo.
  echo   OfficeMind - paste your raw notes below.
  echo   When you are done press Ctrl-Z then Enter.
  echo.
  python -m office_agent -t all
) else (
  python -m office_agent %*
)

echo.
pause
goto :eof

:nopython
echo.
echo Python was not found. Install Python 3.10+ from https://python.org
echo and tick "Add Python to PATH" during setup, then run this file again.
pause
