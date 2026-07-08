#!/bin/sh
# =============================================================================
# release.sh — 统一发布入口
#
# 职责: 一条命令完成版本发布: sync → commit → tag → [push] [install]
# 替代: 旧 pre-push hook + install-hooks.sh + 手动步骤
#
# 用法:
#   bash scripts/release.sh 0.9.12              # commit + tag 仅本地
#   bash scripts/release.sh 0.9.12 --push       # + 推送到 origin
#   bash scripts/release.sh 0.9.12 --push --install  # + pip install -e .
#   bash scripts/release.sh 0.9.12 --install    # + 仅本地安装
#   bash scripts/release.sh 0.9.12 --dry-run    # 试运行，不实际修改
#
# 依赖: git, sed, pip (仅 --install)
# =============================================================================
set -e

DRY_RUN=false

VERSION="$1"
[ -z "$VERSION" ] && {
    echo "Usage: bash scripts/release.sh VERSION [--push] [--install] [--dry-run]"
    echo "  VERSION must be semver (e.g. 0.9.12)"
    exit 1
}
echo "$VERSION" | grep -qE '^[0-9]+\.[0-9]+\.[0-9]+$' || {
    echo "❌ VERSION must be semver (e.g. 0.9.12), got: $VERSION"
    exit 1
}
shift

# 切换到项目根目录
cd "$(dirname "$0")/.."

# 确保工作树干净（保护未提交的修改）
[ -z "$(git status --porcelain pyproject.toml hfpapers/__init__.py 2>/dev/null)" ] || {
    echo "⚠️  pyproject.toml or hfpapers/__init__.py has uncommitted changes."
    echo "   Commit or stash them first, then retry."
    exit 1
}

# 解析 flags
for arg in "$@"; do
    case "$arg" in
        --dry-run) DRY_RUN=true ;;
        --push|--install) ;;  # handled later
        *) echo "⚠️  Unknown flag: $arg (ignored)" ;;
    esac
done

echo ""
echo "╔══════════════════════════════════════╗"
echo "║  Release v$VERSION"
[ "$DRY_RUN" = true ] && echo "║  [DRY RUN — no changes will be made]"
echo "╚══════════════════════════════════════╝"
echo ""

if [ "$DRY_RUN" = false ]; then
    # ---- 1. Sync pyproject.toml ----
    sed -i "s/^version = \".*\"/version = \"$VERSION\"/" pyproject.toml
    echo "✅ pyproject.toml → v$VERSION"

    # ---- 2. Sync __init__.py (hardcoded fallback) ----
    sed -i "s/^__version__ = \".*\"/__version__ = \"$VERSION\"/" hfpapers/__init__.py
    echo "✅ hfpapers/__init__.py → v$VERSION"

    # ---- 3. Commit ----
    git add pyproject.toml hfpapers/__init__.py
    git commit -m "v$VERSION: release"
    echo "✅ Committed v$VERSION ($(git rev-parse --short HEAD))"

    # ---- 4. Tag ----
    git tag "v$VERSION"
    echo "✅ Tagged v$VERSION"

    # ---- 5. Optional actions ----
    PUSHED=false
    INSTALLED=false

    for arg in "$@"; do
        case "$arg" in
            --push)
                git push origin main --tags
                PUSHED=true
                ;;
            --install)
                pip install -e . --quiet
                INSTALLED=true
                ;;
        esac
    done
else
    echo "[DRY-RUN] Would sync pyproject.toml → v$VERSION"
    echo "[DRY-RUN] Would sync __init__.py → v$VERSION"
    echo "[DRY-RUN] Would commit + tag v$VERSION"

    for arg in "$@"; do
        case "$arg" in
            --push)     echo "[DRY-RUN] Would git push origin main --tags" ;;
            --install)  echo "[DRY-RUN] Would pip install -e ." ;;
        esac
    done
fi

echo ""
echo "╔══════════════════════════════════════╗"
echo "║  🎉 Release v$VERSION done!          ║"
if [ "$DRY_RUN" = false ]; then
    [ "$PUSHED" = true ] && echo "║  📤 Pushed to origin"
    [ "$INSTALLED" = true ] && echo "║  📦 Installed locally"
    echo "║  🔖 Tag: v$VERSION"
    echo "║  📍 Commit: $(git rev-parse --short HEAD)"
else
    echo "║  🏁 DRY RUN — nothing was modified  ║"
fi
echo "╚══════════════════════════════════════╝"
