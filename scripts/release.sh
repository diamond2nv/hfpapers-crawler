#!/bin/sh
# =============================================================================
# release.sh — 统一发布入口
#
# 设计原则 (PEP 621):
#   pyproject.toml 是唯一版本源。__init__.py 应动态读取 (importlib.metadata / tomllib)，
#   不同步写。详见 skill version-management SKILL.md。
#
# 用法:
#   bash scripts/release.sh 0.9.12              # commit + tag 仅本地
#   bash scripts/release.sh 0.9.12 --push       # + 推送到 origin
#   bash scripts/release.sh 0.9.12 --dry-run    # 试运行，不实际修改
#
# 依赖: git, sed
# =============================================================================
set -e

DRY_RUN=false

# ── 模板参数（由 install.sh 自动替换）──
BRANCH="main"

VERSION="$1"
[ -z "$VERSION" ] && {
    echo "Usage: bash scripts/release.sh VERSION [--push] [--dry-run]"
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

# 确保工作树干净
[ -z "$(git status --porcelain pyproject.toml 2>/dev/null)" ] || {
    echo "⚠️  pyproject.toml has uncommitted changes."
    echo "   Commit or stash first, then retry."
    exit 1
}

# ---- 0. Changelog coverage ----
# A version may not be tagged while it is undocumented: the repository once shipped
# 18 releases (v0.17.0 - v0.18.14) with no entries because nothing checked.
# Single source of the rule: scripts/changelog_guard.py (also used by the gate test).
if [ -f scripts/changelog_guard.py ]; then
    python3 scripts/changelog_guard.py "$VERSION" || {
        echo "❌ Refusing to release v$VERSION: add its changelog entry first (see docs/CHANGELOG.md)."
        exit 1
    }
else
    echo "⚠️  scripts/changelog_guard.py missing — changelog coverage NOT checked."
fi

# ---- 0a. Header truth ----
# The window comment declares its own byte count; a stale number is worse than no number. Refresh
# it before anything else looks at the window (also the consumer that keeps --refresh alive).
if [ -f scripts/changelog_rotate.py ]; then
    python3 scripts/changelog_rotate.py --refresh || true
fi

# ---- 0b. Changelog window ----
# The changelog is read, not diffed: it must stay a bounded window, with the older
# entries rotated into docs/CHANGELOG-archive.md (rule: scripts/changelog_rotate.py).
if [ -f scripts/changelog_rotate.py ]; then
    python3 scripts/changelog_rotate.py --check || {
        echo "❌ Refusing to release v$VERSION: rotate the changelog window first."
        exit 1
    }
    python3 scripts/changelog_rotate.py --verify-history || {
        echo "❌ Refusing to release v$VERSION: a changelog entry disappeared (live + archive)."
        exit 1
    }
else
    echo "⚠️  scripts/changelog_rotate.py missing — changelog window NOT checked."
fi

# ---- 0c. Version consistency (pre-bump) ----
# The tree must already agree with the latest tag before it is bumped: otherwise a drifted
# pyproject silently turns into "the new version" and the drift is never seen. This is also the
# consumer that keeps scripts/version-check.sh alive (2026-10-26: it had none).
if [ -f scripts/version-check.sh ]; then
    sh scripts/version-check.sh || {
        echo "❌ Refusing to release v$VERSION: pyproject.toml 与最新 tag 不一致。"
        echo "   先对齐：bash scripts/version-check.sh --fix"
        exit 1
    }
else
    echo "⚠️  scripts/version-check.sh missing — pre-bump version consistency NOT checked."
fi

# 解析 flags
for arg in "$@"; do
    case "$arg" in
        --dry-run) DRY_RUN=true ;;
        --push)
            # AGENTS.md: 推送开发线用 `git push forgejo vX.Y.Z && git push forgejo main`。
            # 这里过去的 --push 走 origin（实验室内部 GitLab）并带 --tags，是一条会绕过
            # 开发线/公开线区分的旁路 —— 2026-10-26 起公开线只接受 sanitized 快照，故禁用。
            echo "❌ --push 已禁用：本脚本只做本地 commit + tag。" >&2
            echo "   开发线： git push forgejo v$VERSION && git push forgejo main" >&2
            echo "   公开线： python3 scripts/recut-public.py --mode sync --version $VERSION --push" >&2
            exit 2
            ;;
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
    # ---- 1. Sync pyproject.toml (唯一版本源) ----
    sed -i "s/^version = \"[^\"]*\".*/version = \"$VERSION\"/" pyproject.toml
    echo "✅ pyproject.toml → v$VERSION"

    # ---- 2. Commit ----
    git add pyproject.toml
    git commit -m "v$VERSION: release"
    echo "✅ Committed v$VERSION ($(git rev-parse --short HEAD))"

    # ---- 3. Tag ----
    git tag "v$VERSION"
    echo "✅ Tagged v$VERSION"

    # ---- 4. Push is deliberately not done here ----
    # AGENTS.md: `git push forgejo v$VERSION && git push forgejo main`; the public line goes
    # through recut-public.py. Keeping a push path inside this script is what produced the
    # `--tags` bypass that could leak development tags.
    echo "ℹ️  本地 commit + tag 完毕；推送见 AGENTS.md（forgejo / recut-public.py）"
else
    echo "[DRY-RUN] Would sync pyproject.toml → v$VERSION"
    echo "[DRY-RUN] Would commit + tag v$VERSION"
fi

echo ""
echo "╔══════════════════════════════════════╗"
echo "║  🎉 Release v$VERSION done!          ║"
if [ "$DRY_RUN" = false ]; then
    echo "║  🔖 Tag: v$VERSION"
    echo "║  📍 Commit: $(git rev-parse --short HEAD)"
else
    echo "║  🏁 DRY RUN — nothing was modified  ║"
fi
echo "╚══════════════════════════════════════╝"
