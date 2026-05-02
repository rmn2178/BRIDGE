#!/usr/bin/env bash
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"

cd "$ROOT_DIR"

if [ -d ".venv" ]; then
  chmod +x "$0"
  . .venv/bin/activate
fi

python -m pip install --upgrade pip
pip install -r requirements.txt
pip install pytest pytest-asyncio respx httpx

pytest tests/ -v --tb=short --no-header
RESULT=$?

if [ "$RESULT" -eq 0 ]; then
  echo "All tests passed."
  exit 0
fi

echo "One or more tests failed."
exit 1
