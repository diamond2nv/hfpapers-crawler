#!/bin/bash
# install-hooks.sh — Install git hooks for hfpclawer repo
# Run after clone:  bash scripts/install-hooks.sh
set -e
REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
HOOK_SRC="$REPO_DIR/scripts/pre-push"
HOOK_DST="$REPO_DIR/.git/hooks/pre-push"

if [ -f "$HOOK_DST" ]; then
    echo "⚠️  Pre-push hook already exists at $HOOK_DST"
    echo "   Overwrite? [y/N]"
    read -r answer
    if [ "$answer" != "y" ] && [ "$answer" != "Y" ]; then
        echo "Skipped."
        exit 0
    fi
fi

if [ -f "$HOOK_SRC" ]; then
    cp "$HOOK_SRC" "$HOOK_DST"
    chmod +x "$HOOK_DST"
    echo "✅ Pre-push hook installed: $HOOK_DST"
else
    echo "❌ Template not found: $HOOK_SRC"
    exit 1
fi

# Also install version-check.sh (called by hook, but standalone too)
if [ -f "$REPO_DIR/scripts/version-check.sh" ]; then
    chmod +x "$REPO_DIR/scripts/version-check.sh"
    echo "✅ version-check.sh executable"
fi

echo ""
echo "Next push will verify: pyproject.toml version == latest git tag"
echo "Run manually:  bash scripts/version-check.sh"
