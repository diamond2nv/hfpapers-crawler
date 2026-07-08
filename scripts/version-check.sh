#!/bin/bash
# version-check.sh — Verify pyproject.toml version matches latest git tag
# Exit 1 if version drift detected.
set -e
REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_DIR"

# Get version from pyproject.toml
PY_VERSION=$(grep '^version' pyproject.toml | sed 's/version = "\(.*\)"/\1/')
echo "pyproject.toml:   v$PY_VERSION"

# Get latest git tag
GIT_TAG=$(git tag --sort=-v:refname | grep -E '^v[0-9]+\.[0-9]+\.[0-9]+$' | head -1)
echo "latest git tag:   $GIT_TAG"

if [ -z "$GIT_TAG" ]; then
    echo "⚠️  No git tags found."
    exit 0
fi

GIT_VERSION="${GIT_TAG#v}"

if [ "$PY_VERSION" != "$GIT_VERSION" ]; then
    echo "❌ VERSION DRIFT: pyproject.toml ($PY_VERSION) != git tag ($GIT_VERSION)"
    echo "   Run: sed -i 's/version = \"$PY_VERSION\"/version = \"$GIT_VERSION\"/' pyproject.toml"
    exit 1
fi

echo "✅ Version is consistent."
