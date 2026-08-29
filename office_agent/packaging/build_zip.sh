#!/usr/bin/env bash
# Build officemind.zip — a self-contained folder the user can unzip and run.
#   ./office_agent/packaging/build_zip.sh [output_dir]
set -euo pipefail

repo="$(cd "$(dirname "$0")/../.." && pwd)"
out_dir="${1:-$repo/dist}"
stage="$(mktemp -d)"
pkg="$stage/officemind"

mkdir -p "$pkg/tests"
cp -r "$repo/office_agent" "$pkg/"
rm -rf "$pkg/office_agent/packaging"
cp "$repo/tests/test_office_agent.py" "$pkg/tests/"
cp "$repo/office_agent/packaging/START-HERE.md" \
   "$repo/office_agent/packaging/run.sh" \
   "$repo/office_agent/packaging/run.bat" \
   "$repo/office_agent/packaging/requirements.txt" "$pkg/"
chmod +x "$pkg/run.sh"
find "$pkg" -name '__pycache__' -type d -exec rm -rf {} + 2>/dev/null || true

mkdir -p "$out_dir"
rm -f "$out_dir/officemind.zip"
(cd "$stage" && zip -qr "$out_dir/officemind.zip" officemind)
rm -rf "$stage"

echo "built $out_dir/officemind.zip"
unzip -l "$out_dir/officemind.zip" | tail -1
