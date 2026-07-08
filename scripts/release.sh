#!/bin/bash
# release.sh — 发布新版本：同步 pyproject.toml → commit → tag → push
#
# 用法:
#   bash scripts/release.sh 0.9.12      # 发布 v0.9.12
#   bash scripts/release.sh minor       # bump minor: 0.9.11 → 0.10.0
#   bash scripts/release.sh patch       # bump patch: 0.9.11 → 0.9.12
#   bash scripts/release.sh             # 自动 bump patch
#
# 设计原理: 单一入口点保证 pyproject.toml 版本与 git tag 永远一致。
# 不再手动 git tag v0.x.y —— 全部走此脚本。
set -e

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_DIR"

# ── 获取当前版本 ──────────────────────────────
CUR_VERSION=$(grep '^version' pyproject.toml | sed 's/version = "\(.*\)"/\1/')
echo "Current version: v$CUR_VERSION"

# ── 解析新版本 ────────────────────────────────
NEW_VERSION=""
case "${1:-auto}" in
    auto|patch)
        # v0.9.11 → v0.9.12
        NEW_VERSION=$(echo "$CUR_VERSION" | awk -F. '{printf "%d.%d.%d", $1, $2, $3+1}')
        ;;
    minor)
        # v0.9.11 → v0.10.0
        NEW_VERSION=$(echo "$CUR_VERSION" | awk -F. '{printf "%d.%d.0", $1, $2+1}')
        ;;
    major)
        # v0.9.11 → v1.0.0  (但目前版本号规则 0.x.y，不适用)
        echo "❌ Major bump (v1.0.0+) is outside current 0.x.y convention."
        exit 1
        ;;
    *)
        # 显式版本号
        NEW_VERSION="$1"
        ;;
esac

# 验证版本号格式
if ! echo "$NEW_VERSION" | grep -qE '^[0-9]+\.[0-9]+\.[0-9]+$'; then
    echo "❌ Invalid version format: '$NEW_VERSION' (expected x.y.z)"
    exit 1
fi

# ── 检查是否有未提交变更 ─────────────────────
if [ -n "$(git status --porcelain 2>/dev/null)" ]; then
    echo "⚠️  Uncommitted changes detected. Commit or stash first."
    echo "   Status:"
    git status --short
    exit 1
fi

echo "New version:     v$NEW_VERSION"

# ── 步骤 1: 更新 pyproject.toml ───────────────
sed -i "s/version = \"$CUR_VERSION\"/version = \"$NEW_VERSION\"/" pyproject.toml
echo "✅ pyproject.toml updated: $CUR_VERSION → $NEW_VERSION"

# ── 步骤 2: commit ───────────────────────────
git add pyproject.toml
git commit -m "v$NEW_VERSION: bump version for release"
echo "✅ Committed"

# ── 步骤 3: tag ──────────────────────────────
git tag "v$NEW_VERSION"
echo "✅ Tagged: v$NEW_VERSION"

# ── 步骤 4: push ─────────────────────────────
echo ""
echo "Ready to push:"
echo "  git push origin main:master"
echo "  git push origin v$NEW_VERSION"
echo ""
echo "Push now? [Y/n]"
read -r answer
if [ "$answer" != "n" ] && [ "$answer" != "N" ]; then
    git push origin main:master 2>&1 | tail -1
    git push origin "v$NEW_VERSION" 2>&1 | tail -1
    echo "✅ Pushed v$NEW_VERSION"
else
    echo "Push deferred. Run manually."
fi

# ── 步骤 5: rebuild + reinstall (可选) ────────
echo ""
echo "Rebuild and reinstall? [y/N]"
read -r answer
if [ "$answer" = "y" ] || [ "$answer" = "Y" ]; then
    python3 -m build --no-isolation 2>&1 | tail -1
    pip3 install "dist/hfpclawer-$NEW_VERSION-py3-none-any.whl" --force-reinstall 2>&1 | tail -3
    echo "✅ Reinstalled v$NEW_VERSION"
fi
