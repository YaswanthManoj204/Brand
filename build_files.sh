#!/bin/bash
# Build script executed by Vercel during deployment build phase
echo "=== Installing Python dependencies ==="
python3 -m pip install -r requirements.txt

echo "=== Collecting Django static files ==="
python3 backend/manage.py collectstatic --noinput --clear

echo "=== Build Complete ==="

