#!/usr/bin/env bash
# One-command start for the personal agent.
#   ./run.sh              -> chat
#   ./run.sh "hi there"   -> ask one thing and exit
set -e
cd "$(dirname "$0")"

PY=$(command -v python3 || command -v python || true)
if [ -z "$PY" ]; then
    echo "Python 3.11+ is required but wasn't found. Install it from https://python.org"
    exit 1
fi

if ! "$PY" -c "import openai, rich" >/dev/null 2>&1; then
    echo "Installing dependencies (one time)..."
    "$PY" -m pip install --quiet --disable-pip-version-check rich openai
fi

if [ -z "$DEEPSEEK_API_KEY" ] && [ -z "$ANTHROPIC_API_KEY" ]; then
    echo "No API key found. Get one at https://platform.deepseek.com/api_keys"
    printf "Paste your DeepSeek API key: "
    read -r key
    export DEEPSEEK_API_KEY="$key"
    echo
    echo "Tip: add this line to your ~/.bashrc to skip this next time:"
    echo "  export DEEPSEEK_API_KEY=\"$key\""
    echo
fi

exec "$PY" chat.py "$@"
