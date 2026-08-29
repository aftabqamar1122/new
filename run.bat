@echo off
REM One-command start for the personal agent (Windows).
cd /d "%~dp0"

where python >nul 2>&1
if errorlevel 1 (
    echo Python 3.11+ is required but wasn't found. Install it from https://python.org
    exit /b 1
)

python -c "import openai, rich" >nul 2>&1
if errorlevel 1 (
    echo Installing dependencies ^(one time^)...
    python -m pip install --quiet --disable-pip-version-check rich openai
)

if "%DEEPSEEK_API_KEY%"=="" if "%ANTHROPIC_API_KEY%"=="" (
    echo No API key found. Get one at https://platform.deepseek.com/api_keys
    set /p DEEPSEEK_API_KEY="Paste your DeepSeek API key: "
)

python chat.py %*
