#!/bin/sh
# =============================================================================
# version-check.sh — CI 版本一致性门禁
#
# 职责: 检查 pyproject.toml version 是否与最新 git tag 一致
#       退出码:
#         0 = 一致
#         1 = 不一致（CI 应阻止发布）
#
# 用法:
#   bash scripts/version-check.sh        # 检查当前工作树
#   bash scripts/version-check.sh --fix  # 自动修复 pyproject.toml 对齐 tag
# =============================================================================
set -e

cd "$(dirname "$0")/.."

PY_VERSION=$(grep '^version' pyproject.toml | sed 's/version = "\(.*\)"/\1/')
GIT_TAG=$(git tag --sort=-v:refname | grep -E '^v[0-9]+\.[0-9]+\.[0-9]+$' | head -1)
GIT_VERSION="${GIT_TAG#v}"

[ -z "$GIT_TAG" ] && {
    echo "⚠️  No semver tags found (e.g. v0.9.11). Nothing to check."
    exit 0
}

if [ "$PY_VERSION" != "$GIT_VERSION" ]; then
    if [ "$1" = "--fix" ]; then
        sed -i "s/^version = \".*\"/version = \"$GIT_VERSION\"/" pyproject.toml
        echo "🔧 Fixed pyproject.toml: $PY_VERSION → $GIT_VERSION (matches tag $GIT_TAG)"
        exit 0
    fi
    echo "❌ Version mismatch:"
    echo "   pyproject.toml: $PY_VERSION"
    echo "   latest tag:     $GIT_TAG"
    echo ""
    echo "   To fix: bash scripts/version-check.sh --fix"
    echo "   Or use: bash scripts/release.sh <VERSION>"
    exit 1
fi

echo "✅ Version consistent: $PY_VERSION (matches tag $GIT_TAG)"
