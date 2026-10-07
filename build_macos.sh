#!/usr/bin/env bash
# Construye DriloReview para macOS: dist/DriloReview.app y el zip.
# Crea el entorno .venv si hace falta y llama a build.py, que hace el resto.
# Con CODESIGN_IDENTITY="Developer ID Application: ..." se firma con ese
# certificado; si no, con firma ad hoc.
set -euo pipefail
cd "$(dirname "$0")"
PY=.venv/bin/python
if [ ! -x "$PY" ]; then
    python3 -m venv .venv
    "$PY" -m pip install --upgrade pip
fi
"$PY" -m pip install --quiet PySide6-Essentials pyinstaller
exec "$PY" build.py
