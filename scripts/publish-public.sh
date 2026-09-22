#!/bin/sh
# =============================================================================
# publish-public.sh — 公开发布线（GitHub / Aliyun）发布入口
#
# 为什么存在（2026-09-11）:
#   公开线是一次「重写过的血统」，只能单提交/单补丁落上去，不能推整条本地分支。
#   本次手工做了 worktree → 脱敏 → amend 署名 → tag → push，手搓一遍就推错了一次
#   （在 detached HEAD 的 worktree 里 `git push github master`，推的是主仓库里那
#   个陈旧 local master）。这个脚本把那套顺序固化，并强制几项检查。
#
# 公共线本地分支约定:
#   `public` 跟踪 `github/master`（默认分支名就叫 master）。
#   ✅ 推送必须写 `git push github public:master`
#   ❌ 永远不要写 `git push github master` —— 那会去找本地 `master` 分支
#
# ⛔ 授权范围（2026-09-11 用户明确）:
#   三台机器中**只有本机持有 GitHub 发布凭据**，仅本机被授权发布公开线。
#   其他机器（含局域网内的其他 Hermes 实例）没有 push 权限 —— 它们的工作流是
#   「推到 NAS → 由本机 review 后再发布」。因此在别的机器上跑本脚本会在 push
#   一步失败，这是预期行为，不是脚本坏了。不要为了绕过而在别的机器上找凭据。
#
# 用法:
#   bash scripts/publish-public.sh --status            # 现状：public vs main 分歧、待推内容
#   bash scripts/publish-public.sh --check             # 只跑脱敏门禁（不改任何东西）
#   bash scripts/publish-public.sh 0.17.3              # 打 tag（本地）
#   bash scripts/publish-public.sh 0.17.3 --push       # 打 tag + 推送 public:master + tag
#
# 修版规矩（2026-09-17 起，用户明确）: 公开线**与 PyPI 版本号对齐** —— 本项目的 PyPI 只收
#   `0.x.0` 且 x 为奇数（0.19.0、0.21.0…），公开线就用这套号；旧 0.17.x 序列已废弃。
#
# Tag 命名空间（对齐带来的必然结果）: 同一个版本号在两条血统里各有一个提交，而一个仓库的
#   tag 命名空间是共享的。所以**公开线的 tag 在本地叫 `public-vX.Y.Z`**，推送时用显式 refspec
#   落到远端的真名 `refs/tags/vX.Y.Z`。开发线自己的 `vX.Y.Z` 因此永远不被移动。
#   ⚠️ 推论：在本仓 `git fetch --tags github` 会与开发线同名 tag 冲突 —— 校验用 `git ls-remote`。
# =============================================================================
set -e

PUBLIC_BRANCH="public"
PUBLIC_REMOTE="github"
PUBLIC_REMOTE_BRANCH="master"

die() { echo "❌ $1" >&2; exit 1; }

# ── 脱敏门禁（模式定义在 scripts/sanitize-patterns.sh，与 pre-push / 测试共用）──
_here=$(dirname "$0")
for _cand in "$_here/sanitize-patterns.sh" "scripts/sanitize-patterns.sh"; do
    if [ -f "$_cand" ]; then . "$_cand"; break; fi
done
[ -n "$SENSITIVE_PAT" ] || die "scripts/sanitize-patterns.sh 未找到 —— 脱敏门禁无法运行"

sanitize_gate() {
    _ref="$1"
    ALLOW="$SENSITIVE_ALLOW"
    PAT="$SENSITIVE_PAT"
    _hits=$(git grep -nE "$PAT" "$_ref" 2>/dev/null \
        | grep -vE "$OK_PLACEHOLDER" \
        | grep -vE "$ALLOW" || true)
    if [ -n "$_hits" ]; then
        echo "🔒 脱敏门禁未通过 —— 以下内容不得进公开仓:" >&2
        echo "$_hits" | head -20 >&2
        echo "" >&2
        echo "  占位符规范见 AGENTS.md 表格（ORCID → 0000-0002-1825-0097, 姓名 → Jane Doe / 张三）" >&2
        return 1
    fi

    # 内网布局与项目代号：只豁免门禁脚本自身（自指）
    _layout=$(git grep -nE "$LAYOUT_PAT" "$_ref" 2>/dev/null \
        | grep -vE "$LAYOUT_ALLOW" || true)
    if [ -n "$_layout" ]; then
        echo "🔒 内网布局/项目代号门禁未通过 —— 以下内容不得进公开仓:" >&2
        echo "$_layout" | head -20 >&2
        echo "" >&2
        echo "  本地路径与私有仓库名应改为环境声明（HFPCLAWER_PEER_REPOS / HFPCLAWER_REPO_MAP），" >&2
        echo "  真实值放 gitignore 文件；模式定义见 scripts/sanitize-patterns.sh" >&2
        return 1
    fi
    echo "✅ 脱敏门禁通过（敏感值 + 内网布局/项目代号）"
}

MODE=""
VERSION=""
PUSH=false

for arg in "$@"; do
    case "$arg" in
        --status) MODE="status" ;;
        --check)  MODE="check" ;;
        --push)   PUSH=true ;;
        --*)      die "未知参数: $arg" ;;
        *)        VERSION="$arg" ;;
    esac
done

# ── 基本前提 ──
git rev-parse --git-dir >/dev/null 2>&1 || die "不在 git 仓库内"
git show-ref --verify --quiet "refs/heads/$PUBLIC_BRANCH" \
    || die "本地没有 $PUBLIC_BRANCH 分支 —— 先建: git branch $PUBLIC_BRANCH $PUBLIC_REMOTE/$PUBLIC_REMOTE_BRANCH"

# ── --status ──
if [ "$MODE" = "status" ]; then
    echo "本地 $PUBLIC_BRANCH : $(git rev-parse --short "$PUBLIC_BRANCH")  $(git log -1 --format=%s "$PUBLIC_BRANCH" | cut -c1-60)"
    echo "$PUBLIC_REMOTE/$PUBLIC_REMOTE_BRANCH : $(git rev-parse --short "$PUBLIC_REMOTE/$PUBLIC_REMOTE_BRANCH")"
    echo ""
    if git merge-base --is-ancestor "$PUBLIC_REMOTE/$PUBLIC_REMOTE_BRANCH" "$PUBLIC_BRANCH"; then
        n=$(git rev-list --count "$PUBLIC_REMOTE/$PUBLIC_REMOTE_BRANCH..$PUBLIC_BRANCH")
        echo "待推公开线的提交: $n 个"
        [ "$n" -gt 0 ] && git log --oneline "$PUBLIC_REMOTE/$PUBLIC_REMOTE_BRANCH..$PUBLIC_BRANCH"
    else
        echo "⚠️  $PUBLIC_BRANCH 与 $PUBLIC_REMOTE/$PUBLIC_REMOTE_BRANCH 已分叉 —— 先 fetch + 处理，不要强推"
    fi
    echo ""
    echo "公开线 pyproject 版本: $(git show "$PUBLIC_BRANCH:pyproject.toml" | grep '^version' | sed 's/.*"\(.*\)".*/\1/')"
    # 公开线的 tag 在本地叫 public-vX.Y.Z（命名空间对齐，见文件头说明），旧的公开线 tag
    # 叫 vX.Y.Z —— 两种名字都要认，否则这里会退回报一个早已退役的老版本（实测报 v0.17.3）。
    echo "最新公开 tag        : $(git tag --merged "$PUBLIC_BRANCH" 2>/dev/null \
        | sed -n 's/^public-//p' | grep -E '^v[0-9]+\.[0-9]+\.[0-9]+$' | sort -V | tail -1)"
    echo "   （本地 tag 名 public-vX.Y.Z，远端真名 vX.Y.Z；校验远端用 git ls-remote）"
    exit 0
fi

# ── --check（只读）──
if [ "$MODE" = "check" ]; then
    sanitize_gate "$PUBLIC_BRANCH"
    exit $?
fi

# ── 需要 VERSION ──
[ -n "$VERSION" ] || die "用法: bash scripts/publish-public.sh VERSION [--push] | --status | --check"
echo "$VERSION" | grep -qE '^[0-9]+\.[0-9]+\.[0-9]+$' \
    || die "版本号必须是 semver（如 0.17.3），收到: $VERSION"

# ── 前提检查 ──
[ -z "$(git status --porcelain)" ] || die "工作区不干净 —— 先 commit 或 stash，避免把无关改动带上公开线"

CURRENT=$(git rev-parse --abbrev-ref HEAD)
[ "$CURRENT" = "$PUBLIC_BRANCH" ] \
    || die "当前在 $CURRENT，公开线发布必须在 $PUBLIC_BRANCH 分支上操作"

# 公开线版本必须来自它自己的 pyproject（AGENTS.md: 版本号必须派生自 pyproject）
PUB_VERSION=$(git show "$PUBLIC_BRANCH:pyproject.toml" | grep '^version' | sed 's/.*"\(.*\)".*/\1/')
[ "$PUB_VERSION" = "$VERSION" ] \
    || die "$PUBLIC_BRANCH 的 pyproject 是 $PUB_VERSION，与要发布的 $VERSION 不符 —— 先 bump pyproject"

# 公开线专属 tag 名 —— 开发线的同名 tag（v$VERSION）存在于本仓是正常现象，不再拒绝
PUBLIC_TAG="public-v$VERSION"
if git rev-parse -q --verify "refs/tags/$PUBLIC_TAG" >/dev/null; then
    _at=$(git rev-parse "$PUBLIC_TAG^{commit}")
    _want=$(git rev-parse "$PUBLIC_BRANCH^{commit}")
    [ "$_at" = "$_want" ] || die "$PUBLIC_TAG 已存在且指向 $_at，与 $PUBLIC_BRANCH 的 $_want 不同（不要移动已发布的 tag；换个版本号）"
    echo "ℹ️  $PUBLIC_TAG 已存在且指向同一提交，沿用"
fi
# 远端同名 tag 若已存在且提交不同，才是真的「移动已发布 tag」
_remote_at=$(git ls-remote "$PUBLIC_REMOTE" "refs/tags/v$VERSION^{}" 2>/dev/null | cut -f1 || true)
_public_sha=$(git rev-parse "$PUBLIC_BRANCH^{commit}")
if [ -n "$_remote_at" ] && [ "$_remote_at" != "$_public_sha" ]; then
    die "远端已有 v$VERSION 指向另一提交（${_remote_at%"${_remote_at#????????}"}…）—— 不移动已发布的 tag，换个版本号或先确认远端"
fi

echo ""
echo "── 将发布到 $PUBLIC_REMOTE/$PUBLIC_REMOTE_BRANCH ──"
echo "  提交:   $(git rev-parse --short "$PUBLIC_BRANCH") $(git log -1 --format=%s "$PUBLIC_BRANCH" | cut -c1-60)"
echo "  版本:   v$VERSION"
echo "  署名:   $(git log -1 --format='%an <%ae>' "$PUBLIC_BRANCH")"
echo ""

# 署名必须是公开线统一身份（amend 时 author 与 committer 都要改）
AUTHOR_EMAIL=$(git log -1 --format='%ae' "$PUBLIC_BRANCH")
case "$AUTHOR_EMAIL" in
    *@zhejianglab.org) ;;  # 公开线统一署名
    *) echo "⚠️  公开线署名是 $AUTHOR_EMAIL —— 确认这是有意公开的身份（见 skill 坑②）" ;;
esac

sanitize_gate "$PUBLIC_BRANCH" || die "脱敏门禁未通过，已中止"

echo ""
echo "── 打 annotated tag（本地名 $PUBLIC_TAG，远端名 v$VERSION）──"
git tag -a "$PUBLIC_TAG" -m "v$VERSION — public snapshot, version-aligned with PyPI" --force
echo "✅ 已打 tag $PUBLIC_TAG -> $(git rev-parse --short "$PUBLIC_TAG^{commit}")"

if [ "$PUSH" = "true" ]; then
    echo ""
    echo "── 推送（先 tag 后分支；远程分支名不变，用显式 refspec public:master）──"
    git push "$PUBLIC_REMOTE" "refs/tags/$PUBLIC_TAG:refs/tags/v$VERSION"
    git push "$PUBLIC_REMOTE" "$PUBLIC_BRANCH:$PUBLIC_REMOTE_BRANCH"
    echo ""
    echo "── 读回验证（不采信推送回执）──"
    git fetch -q "$PUBLIC_REMOTE"
    echo "  远程 $PUBLIC_REMOTE_BRANCH : $(git rev-parse --short "$PUBLIC_REMOTE/$PUBLIC_REMOTE_BRANCH")"
    echo "  本地 $PUBLIC_BRANCH        : $(git rev-parse --short "$PUBLIC_BRANCH")"
    echo "  远程 tag v$VERSION         : $(git ls-remote "$PUBLIC_REMOTE" "refs/tags/v$VERSION^{}" | cut -f1 | cut -c1-8)"
else
    echo ""
    echo "（未加 --push，仅本地打 tag；推送请重跑并加 --push，或用:）
  git push $PUBLIC_REMOTE refs/tags/$PUBLIC_TAG:refs/tags/v$VERSION && git push $PUBLIC_REMOTE $PUBLIC_BRANCH:$PUBLIC_REMOTE_BRANCH"
fi
