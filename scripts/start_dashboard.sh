#!/bin/bash
# =====================================================
# Trader Machine — Dashboard V2 Launcher (macOS)
# =====================================================
set -e

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$DIR"

echo "=============================================="
echo "  TRADER MACHINE — DASHBOARD V2"
echo "  URL: http://localhost:5050"
echo "=============================================="

if [ ! -d ".venv" ]; then
  echo "ERROR: .venv not found. Run: python3 -m venv .venv && .venv/bin/pip install -r requirements.txt"
  exit 1
fi

.venv/bin/python apps/dashboard/server.py
