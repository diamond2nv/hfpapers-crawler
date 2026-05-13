#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────
# publish.sh — Build & upload hfpclawer to PyPI
# Usage: bash scripts/publish.sh [test|prod]
#   test: upload to TestPyPI first
#   prod: upload to real PyPI
# ─────────────────────────────────────────────────────────
set -euo pipefail

HERE="$(cd "$(dirname "$0")/.." && pwd)"
cd "$HERE"

# ── Sanity checks ────────────────────────────────────────
if ! command -v twine &>/dev/null; then
  echo "Installing twine..."
  pip install twine build
fi

if [ "$(git status --porcelain | wc -l)" -gt 0 ]; then
  echo "❗ Uncommitted changes detected. Commit or stash first."
  git status --short
  exit 1
fi

VERSION="$(python3 -c "import hfpclawer; print(hfpclawer.__version__)")"
echo "📦 Building hfpclawer v${VERSION}..."

# ── Build ─────────────────────────────────────────────────
rm -rf dist/ build/ *.egg-info
python3 -m build

echo ""
echo "📦 Build artifacts:"
ls -1 dist/

# ── Upload ────────────────────────────────────────────────
MODE="${1:-test}"

if [ "$MODE" = "test" ]; then
  echo ""
  echo "🚀 Uploading to TestPyPI..."
  twine upload --repository-url https://test.pypi.org/legacy/ dist/*
  echo ""
  echo "✅ Done! Install from TestPyPI:"
  echo "   pip install --index-url https://test.pypi.org/simple/ hfpclawer"
elif [ "$MODE" = "prod" ]; then
  echo ""
  echo "🚀 Uploading to PyPI..."
  twine upload dist/*
  echo ""
  echo "✅ Published to PyPI:"
  echo "   pip install hfpclawer"
else
  echo "Unknown mode: $MODE (use 'test' or 'prod')"
  exit 1
fi

echo ""
echo "🏷️  Tag this release?"
echo "   git tag v${VERSION} && git push origin v${VERSION}"
