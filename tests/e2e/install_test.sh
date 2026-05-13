#!/usr/bin/env bash
# ─── E2E 安装验证脚本 ─────────────────────────
# 模拟第三方用户安装 hfpclawer:
#   pip install hfpclawer            # 核心安装
#   pip install hfpclawer[llm]       # +LLM
#   pip install hfpclawer[pdf]       # +PDF转换
#
# 用法:
#   bash tests/e2e/install_test.sh
# ====================================================

set -uo pipefail
HERE="$(cd "$(dirname "$0")/../.." && pwd)"
PROJECT_DIR="$HERE"
PASS=0
FAIL=0

red()    { echo -e "\033[31m$*\033[0m"; }
green()  { echo -e "\033[32m$*\033[0m"; }
blue()   { echo -e "\033[34m$*\033[0m"; }
yellow() { echo -e "\033[33m$*\033[0m"; }

assert_eq() {
    local desc="$1" expected="$2" actual="$3"
    if [[ "$actual" == "$expected" ]]; then
        green "    ✅ $desc"
        ((PASS++))
    else
        red "    ❌ $desc (期待 '$expected', 得到 '$actual')"
        ((FAIL++))
    fi
}

assert_contains() {
    local desc="$1" needle="$2" haystack="$3"
    if echo "$haystack" | grep -qF "$needle"; then
        green "    ✅ $desc"
        ((PASS++))
    else
        red "    ❌ Failed: $needle not found"
        echo "    OUTPUT: $(echo "$haystack" | head -3)"
        ((FAIL++))
    fi
}

py() {
    python3 -c "$1" 2>/dev/null || echo "ERROR"
}

cd "$PROJECT_DIR"

blue ""
blue "╔═══════════════════════════════════════════╗"
blue "║   hfpclawer E2E 安装验证                  ║"
blue "╚═══════════════════════════════════════════╝"

# ════════════════════════════════════════════
# 1: pip install hfpclawer（核心）
# ════════════════════════════════════════════
echo ""
blue "📋 1: pip install hfpclawer（核心）"

pip install "$PROJECT_DIR" -q 2>&1 | tail -1 || {
    red "    ❌ pip install 失败"
    exit 1
}

HELP=$(hfpclawer --help 2>&1 || true)
assert_contains "hfpclawer --help 列出 search" "search" "$HELP"
assert_contains "hfpclawer --help 列出 audit" "audit" "$HELP"
assert_contains "hfpclawer --help 列出 mcp" "mcp" "$HELP"
assert_contains "hfpclawer --help 列出 store" "store" "$HELP"
assert_contains "hfpclawer --help 列出 download" "download" "$HELP"

# 核心模块导入
MOD_IMPORT=$(py "
from hfpapers.cli import app; print('cli:ok')
from hfpapers.paper_store import PaperStore; print('store:ok')
from hfpapers.mcp_server import MCP_TOOLS; print(f'mcp:{len(MCP_TOOLS)}')
")
assert_contains "核心模块可导入" "cli:ok" "$MOD_IMPORT"
assert_contains "MCP_TOOLS 有 7 个工具" "mcp:7" "$MOD_IMPORT"

# ════════════════════════════════════════════
# 2: pip install hfpclawer[llm]
# ════════════════════════════════════════════
echo ""
blue "📋 2: pip install hfpclawer[llm] + [pdf]"

pip install "$PROJECT_DIR[llm,pdf]" -q 2>&1 | tail -1 || {
    yellow "    ⚠️  [llm,pdf] 安装可能不完整"
    ((FAIL++))
}

LLM_OK=$(py "from litellm import completion; print('ok')")
assert_contains "litellm 可导入" "ok" "$LLM_OK"

PDF_OK=$(py "import pymupdf4llm; print('ok')")
assert_contains "pymupdf4llm 可导入" "ok" "$PDF_OK"

# ════════════════════════════════════════════
# 3: CLI 离线子命令
# ════════════════════════════════════════════
echo ""
blue "📋 3: CLI 离线子命令"

OUT=$(hfpclawer audit 2>&1 | head -5 || true)
assert_contains "audit 可运行" "审计" "$OUT"

OUT=$(hfpclawer store stats 2>&1 | head -5 || true)
assert_contains "store stats 可运行" "Paper Store" "$OUT"

OUT=$(hfpclawer config 2>&1 || true)
assert_contains "config 可运行" "search" "$OUT"

OUT=$(hfpclawer store export xlsx 2>&1 || true)
assert_contains "store export 报错" "不支持" "$OUT"

OUT=$(hfpclawer dedup 2>&1 || true)
assert_contains "dedup 可运行" "去重" "$OUT"

# ════════════════════════════════════════════
# 4: MCP stdio 协议验证
# ════════════════════════════════════════════
echo ""
blue "📋 4: MCP stdio 协议验证"

MCP_OUT=$(echo '{"jsonrpc":"2.0","id":1,"method":"initialize"}
{"jsonrpc":"2.0","id":2,"method":"tools/list"}' | hfpclawer mcp 2>/dev/null || true)

LINE_CNT=$(echo "$MCP_OUT" | grep -c . || true)
if [[ "$LINE_CNT" -ge 2 ]]; then
    green "    ✅ MCP stdio 返回 $LINE_CNT 行响应"
    ((PASS++))

    TOOL_CNT=$(echo "$MCP_OUT" | tail -1 | python3 -c "
import sys, json
try:
    r = json.load(sys.stdin)
    print(len(r['result']['tools']))
except: print(0)
" 2>/dev/null || echo "0")
    assert_eq "tools/list 返回 7 个工具" "7" "$TOOL_CNT"
else
    red "    ❌ MCP stdio 返回 ${LINE_CNT:-0} 行（期待 ≥2）"
    echo "    OUTPUT: $(echo "$MCP_OUT" | head -5)"
    ((FAIL++))
fi

# ════════════════════════════════════════════
# 汇总
# ════════════════════════════════════════════
echo ""
blue "╔═══════════════════════════════════════════╗"
blue "║      安装验证完成                          ║"
blue "╚═══════════════════════════════════════════╝"
echo ""
green "✅ 通过: $PASS"
if [[ $FAIL -gt 0 ]]; then
    red "❌ 失败: $FAIL"
    exit 1
else
    green "🎉 全部通过!"
    echo ""
    echo "  建议第三方安装方式:"
    echo "    pip install hfpclawer                 # 核心"
    echo "    pip install 'hfpclawer[llm,pdf]'      # 核心 + LLM + PDF"
    echo ""
fi
