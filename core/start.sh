#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
if [[ -x .venv/bin/python ]]; then
  PYTHON=.venv/bin/python
else
  PYTHON="${PYTHON:-python3}"
fi
if [[ "${MIXAMO_NO_BROWSER:-0}" != "1" ]]; then
  if command -v open >/dev/null 2>&1; then
    (sleep 1.5; open 'http://127.0.0.1:5055' >/dev/null 2>&1) &
  elif command -v xdg-open >/dev/null 2>&1; then
    (sleep 1.5; xdg-open 'http://127.0.0.1:5055' >/dev/null 2>&1) &
  fi
fi
exec "$PYTHON" flask_app.py
