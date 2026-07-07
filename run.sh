#!/usr/bin/env bash
set -euo pipefail
# Un solo proceso (Reserved VM): API + worker OCR embebido + estáticos del frontend
exec python -m uvicorn --app-dir backend/src main:app --host 0.0.0.0 --port "${PORT:-8000}"
