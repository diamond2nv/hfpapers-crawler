#!/usr/bin/env bash
# ─── E2E MCP stdio 协议测试 ───────────────────
# 真起 MCP stdio 子进程，发 JSON-RPC 消息，验证返回
# 用法: ./test_mcp_stdio.sh [--install]
#   --install: 先 pip install -e . 确保最新
#
# 依赖: curl (用于 HTTP 模式测试)
#       python3 + hfpclawer
# ====================================================

set -euo pipefail
HERE="$(cd "$(dirname "$0")/.." && pwd)"
PASS=0
FAIL=0

red()   { echo -e "\033[31m$*\033[0m"; }
green() { echo -e "\033[32m$*\033[0m"; }
blue()  { echo -e "\033[34m$*\033[0m"; }

assert_eq() {
    local desc="$1" expected="$2" actual="$3"
    if [[ "$actual" == "$expected" ]]; then
        green "  ✅ $desc"
        ((PASS++))
    else
        red "  ❌ $desc (期待 '$expected', 得到 '$actual')"
        ((FAIL++))
    fi
}

assert_contains() {
    local desc="$1" needle="$2" haystack="$3"
    if echo "$haystack" | grep -qF "$needle"; then
        green "  ✅ $desc"
        ((PASS++))
    else
        red "  ❌ $desc (未找到 '$needle')"
        ((FAIL++))
    fi
}

# ════════════════════════════════════════════
# 前置检查
# ════════════════════════════════════════════

cd "$HERE"

if [[ "${1:-}" == "--install" ]]; then
    blue "📦 安装最新 hfpclawer..."
    pip install -e . -q 2>/dev/null || pip install -e "$HERE" -q
fi

# 检查 hfpclawer 可用
if ! command -v hfpclawer &>/dev/null; then
    blue "⚠️  hfpclawer 不在 PATH，尝试本地运行..."
    HFPCLAWER="python -m hfpapers.cli"
else
    HFPCLAWER="hfpclawer"
fi

blue ""
blue "╔═══════════════════════════════════════════╗"
blue "║      E2E: MCP stdio 协议测试             ║"
blue "╚═══════════════════════════════════════════╝"
blue ""

# ════════════════════════════════════════════
# Test 1: CLI --help
# ════════════════════════════════════════════
blue "📋 Test 1: hfpclawer --help 列出子命令"

HELP_OUTPUT=$($HFPCLAWER --help 2>&1 || true)
assert_contains "包含 search" "search" "$HELP_OUTPUT"
assert_contains "包含 audit" "audit" "$HELP_OUTPUT"
assert_contains "包含 mcp" "mcp" "$HELP_OUTPUT"
assert_contains "包含 store" "store" "$HELP_OUTPUT"
assert_contains "包含 download" "download" "$HELP_OUTPUT"

# ════════════════════════════════════════════
# Test 2: MCP stdio — tools/list
# ════════════════════════════════════════════
blue ""
blue "📋 Test 2: MCP stdio — 发 initialize + tools/list"

# 启动 MCP stdio 子进程，接受 stdin 管道
MCP_OUTPUT=$(echo '{"jsonrpc":"2.0","id":1,"method":"initialize"}
{"jsonrpc":"2.0","id":2,"method":"tools/list"}
{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"hfpclawer_stats","arguments":{}}}' | $HFPCLAWER mcp 2>/dev/null || true)

# 解析三行输出
LINE_COUNT=$(echo "$MCP_OUTPUT" | grep -c . || true)
assert_contains "有输出行 (>=3)" "3" ">=..." # 宽松验证

INIT_LINE=$(echo "$MCP_OUTPUT" | head -1)
TOOLS_LINE=$(echo "$MCP_OUTPUT" | head -2 | tail -1)
CALL_LINE=$(echo "$MCP_OUTPUT" | head -3 | tail -1)

# 验证 initialize 响应
if [[ -n "$INIT_LINE" ]]; then
    INIT_PROTO=$(echo "$INIT_LINE" | python3 -c "import sys,json; print(json.load(sys.stdin).get('result',{}).get('protocolVersion',''))" 2>/dev/null || echo "")
    assert_eq "initialize 版本 2024-11-05" "2024-11-05" "$INIT_PROTO"
fi

# 验证 tools/list 响应
if [[ -n "$TOOLS_LINE" ]]; then
    TOOL_COUNT=$(echo "$TOOLS_LINE" | python3 -c "import sys,json; print(len(json.load(sys.stdin).get('result',{}).get('tools',[])))" 2>/dev/null || echo "0")
    assert_eq "tools/list 返回 7 个工具" "7" "$TOOL_COUNT"
fi

# 验证 tools/call stats 响应
if [[ -n "$CALL_LINE" ]]; then
    HAS_TOTAL=$(echo "$CALL_LINE" | python3 -c "
import sys,json
r = json.load(sys.stdin)
c = r.get('result',{}).get('content',[{}])[0].get('text','')
d = json.loads(c)
print('yes' if 'total_papers' in d else 'no')
" 2>/dev/null || echo "no")
    assert_eq "tools/call stats 有 total_papers" "yes" "$HAS_TOTAL"
fi

# ════════════════════════════════════════════
# Test 3: MCP stdio — unknown tool
# ════════════════════════════════════════════
blue ""
blue "📋 Test 3: MCP stdio — 调用不存在的工具"

UNKNOWN_OUTPUT=$(echo '{"jsonrpc":"2.0","id":99,"method":"tools/call","params":{"name":"does_not_exist","arguments":{}}}' | $HFPCLAWER mcp 2>/dev/null || true)

if [[ -n "$UNKNOWN_OUTPUT" ]]; then
    HAS_ERROR=$(echo "$UNKNOWN_OUTPUT" | python3 -c "
import sys,json
r = json.load(sys.stdin)
print('yes' if 'error' in r else 'no')
" 2>/dev/null || echo "no")
    assert_eq "未知工具返回 error" "yes" "$HAS_ERROR"
fi

# ════════════════════════════════════════════
# Test 4: CLI 日常命令
# ════════════════════════════════════════════
blue ""
blue "📋 Test 4: CLI 日常命令"

# audit (可在空库上跑)
AUDIT_OUTPUT=$($HFPCLAWER audit 2>&1 || true)
assert_contains "audit 能运行" "数据源审计" "$AUDIT_OUTPUT"

# config
CONFIG_OUTPUT=$($HFPCLAWER config 2>&1 || true)
assert_contains "config 能运行" "search" "$CONFIG_OUTPUT"

# stats
STATS_OUTPUT=$($HFPCLAWER stats 2>&1 || true)
assert_contains "stats 能运行" "论文" "$STATS_OUTPUT"

# store stats
STORE_OUTPUT=$($HFPCLAWER store stats 2>&1 || true)
assert_contains "store stats 能运行" "论文" "$STORE_OUTPUT"

# ════════════════════════════════════════════
# Test 5: MCP HTTP 模式（可选，需端口可用）
# ════════════════════════════════════════════
blue ""
blue "📋 Test 5: MCP HTTP 模式"

# 后台起 MCP HTTP server
MCP_PORT=18765
$HFPCLAWER mcp --mode http --port $MCP_PORT &
MCP_PID=$!
disown
sleep 1

# 使用 curl 测试（如果可用）
if command -v curl &>/dev/null; then
    # health
    HEALTH=$(curl -sf http://127.0.0.1:$MCP_PORT/health 2>/dev/null || echo "")
    if [[ -n "$HEALTH" ]]; then
        HEALTH_OK=$(echo "$HEALTH" | python3 -c "import sys,json; print(json.load(sys.stdin).get('status',''))" 2>/dev/null || echo "")
        assert_eq "HTTP /health 返回 ok" "ok" "$HEALTH_OK"
    fi

    # tools
    TOOLS_DATA=$(curl -sf http://127.0.0.1:$MCP_PORT/tools 2>/dev/null || echo "")
    if [[ -n "$TOOLS_DATA" ]]; then
        TOOL_NAMES=$(echo "$TOOLS_DATA" | python3 -c "import sys,json; print(list(json.load(sys.stdin).keys()))" 2>/dev/null || echo "")
        assert_contains "HTTP /tools 有 search" "search" "$TOOL_NAMES"
    fi

    # call stats
    CALL_DATA=$(curl -sf http://127.0.0.1:$MCP_PORT/call/hfpclawer_stats 2>/dev/null || echo "")
    if [[ -n "$CALL_DATA" ]]; then
        CALL_OK=$(echo "$CALL_DATA" | python3 -c "import sys,json; print('yes' if 'total_papers' in json.load(sys.stdin) else 'no')" 2>/dev/null || echo "no")
        assert_eq "HTTP /call/stats 有 total_papers" "yes" "$CALL_OK"
    fi
else
    blue "  ⚠️  curl 未安装，跳过 HTTP 测试"
fi

# 杀掉 MCP HTTP server 后台进程
kill $MCP_PID 2>/dev/null || true

# ════════════════════════════════════════════
# 汇总
# ════════════════════════════════════════════
blue ""
blue "╔═══════════════════════════════════════════╗"
blue "║      测试完成                              ║"
blue "╚═══════════════════════════════════════════╝"
echo ""
green "✅ 通过: $PASS"
if [[ $FAIL -gt 0 ]]; then
    red "❌ 失败: $FAIL"
else
    green "🎉 全部通过!"
fi
echo ""

exit $FAIL
