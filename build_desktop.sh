#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
VENV_PYTHON="$ROOT/.venv/bin/python3"

echo "=== Build Nova Desktop ==="
"$VENV_PYTHON" "$ROOT/build.py" --clean
echo ""
echo "Output: $(ls -d "$ROOT/dist/"*/ 2>/dev/null || echo "$ROOT/dist/")"
