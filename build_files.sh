#!/bin/bash
set -e

echo "=== Installing Python dependencies ==="
if command -v uv &> /dev/null; then
    uv pip install --system -r requirements.txt || uv pip install -r requirements.txt || python3 -m pip install --break-system-packages -r requirements.txt
elif python3 -m pip install --help 2>&1 | grep -q -- '--break-system-packages'; then
    python3 -m pip install --break-system-packages -r requirements.txt
else
    python3 -m pip install -r requirements.txt
fi

echo "=== Collecting Django static files ==="
python3 backend/manage.py collectstatic --noinput --clear

# Ensure staticfiles is present at root staticfiles directory for Vercel
mkdir -p staticfiles
cp -r backend/staticfiles/* staticfiles/ 2>/dev/null || true

echo "=== Build Complete ==="
