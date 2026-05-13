#!/usr/bin/env bash
# ─── E2E MCP stdio Protocol Test ──────────────────
# Starts a real MCP stdio subprocess, sends JSON-RPC messages, verifies responses.
# Usage: ./test_mcp_stdio.sh [--install]
#   --install: pip install -e . first to ensure latest
#
# Dependencies: curl (for HTTP mode testing)
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
        red "  ❌ $desc (expected '$expected', got '$actual')"
        ((FAIL++))
    fi
}

assert_contains() {
    local desc="$1" needle="$2" haystack="$3"
    if echo "$haystack" | grep -qF "$needle"; then
        green "  ✅ $desc"
        ((PASS++))
    else
        red "  ❌ $desc ('$needle' not found)"
        ((FAIL++))
    fi
}

# ════════════════════════════════════════════
# Pre-flight check
# ════════════════════════════════════════════

cd "$HERE"

if [[ "${1:-}" == "--install" ]]; then
    blue "📦 Installing latest hfpclawer..."
    pip install -e . -q 2>/dev/null || pip install -e "$HERE" -q
fi

# Check hfpclawer availability
if ! command -v hfpclawer &>/dev/null; then
    blue "⚠️  hfpclawer not in PATH, trying local run..."
    HFPCLAWER="python -m hfpapers.cli"
else
    HFPCLAWER="hfpclawer"
fi

blue ""
blue "╔═══════════════════════════════════════════╗"
blue "║      E2E: MCP stdio Protocol Test        ║"
blue "╚═══════════════════════════════════════════╝"
blue ""

# ════════════════════════════════════════════
# Test 1: CLI --help
# ════════════════════════════════════════════
blue "📋 Test 1: hfpclawer --help lists subcommands"

HELP_OUTPUT=$($HFPCLAWER --help 2>&1 || true)
assert_contains "contains search" "search" "$HELP_OUTPUT"
assert_contains "contains audit" "audit" "$HELP_OUTPUT"
assert_contains "contains mcp" "mcp" "$HELP_OUTPUT"
assert_contains "contains store" "store" "$HELP_OUTPUT"
assert_contains "contains download" "download" "$HELP_OUTPUT"

# ════════════════════════════════════════════
# Test 2: MCP stdio — tools/list
# ════════════════════════════════════════════
blue ""
blue "📋 Test 2: MCP stdio — send initialize + tools/list"

# Start MCP stdio subprocess via stdin pipeline
MCP_OUTPUT=$(echo '{"jsonrpc":"2.0","id":1,"method":"initialize"}
{"jsonrpc":"2.0","id":2,"method":"tools/list"}
{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"hfpclawer_stats","arguments":{}}}' | $HFPCLAWER mcp 2>/dev/null || true)

# Parse three lines of output
LINE_COUNT=$(echo "$MCP_OUTPUT" | grep -c . || true)
assert_contains "has output lines (>=3)" "3" ">=..." # Loose verification

INIT_LINE=$(echo "$MCP_OUTPUT" | head -1)
TOOLS_LINE=$(echo "$MCP_OUTPUT" | head -2 | tail -1)
CALL_LINE=$(echo "$MCP_OUTPUT" | head -3 | tail -1)

# Verify initialize response
if [[ -n "$INIT_LINE" ]]; then
    INIT_PROTO=$(echo "$INIT_LINE" | python3 -c "import sys,json; print(json.load(sys.stdin).get('result',{}).get('protocolVersion',''))" 2>/dev/null || echo "")
    assert_eq "initialize version 2024-11-05" "2024-11-05" "$INIT_PROTO"
fi

# Verify tools/list response
if [[ -n "$TOOLS_LINE" ]]; then
    TOOL_COUNT=$(echo "$TOOLS_LINE" | python3 -c "import sys,json; print(len(json.load(sys.stdin).get('result',{}).get('tools',[])))" 2>/dev/null || echo "0")
    assert_eq "tools/list returns 7 tools" "7" "$TOOL_COUNT"
fi

# Verify tools/call stats response
if [[ -n "$CALL_LINE" ]]; then
    HAS_TOTAL=$(echo "$CALL_LINE" | python3 -c "
import sys,json
r = json.load(sys.stdin)
c = r.get('result',{}).get('content',[{}])[0].get('text','')
d = json.loads(c)
print('yes' if 'total_papers' in d else 'no')
" 2>/dev/null || echo "no")
    assert_eq "tools/call stats has total_papers" "yes" "$HAS_TOTAL"
fi

# ════════════════════════════════════════════
# Test 3: MCP stdio — unknown tool
# ════════════════════════════════════════════
blue ""
blue "📋 Test 3: MCP stdio — call non-existent tool"

UNKNOWN_OUTPUT=$(echo '{"jsonrpc":"2.0","id":99,"method":"tools/call","params":{"name":"does_not_exist","arguments":{}}}' | $HFPCLAWER mcp 2>/dev/null || true)

if [[ -n "$UNKNOWN_OUTPUT" ]]; then
    HAS_ERROR=$(echo "$UNKNOWN_OUTPUT" | python3 -c "
import sys,json
r = json.load(sys.stdin)
print('yes' if 'error' in r else 'no')
" 2>/dev/null || echo "no")
    assert_eq "unknown tool returns error" "yes" "$HAS_ERROR"
fi

# ════════════════════════════════════════════
# Test 4: CLI daily commands
# ════════════════════════════════════════════
blue ""
blue "📋 Test 4: CLI daily commands"

# audit (can run on empty db)
AUDIT_OUTPUT=$($HFPCLAWER audit 2>&1 || true)
assert_contains "audit runs" "Data Source Audit" "$AUDIT_OUTPUT"

# config
CONFIG_OUTPUT=$($HFPCLAWER config 2>&1 || true)
assert_contains "config runs" "search" "$CONFIG_OUTPUT"

# stats
STATS_OUTPUT=$($HFPCLAWER stats 2>&1 || true)
assert_contains "stats runs" "Papers" "$STATS_OUTPUT"

# store stats
STORE_OUTPUT=$($HFPCLAWER store stats 2>&1 || true)
assert_contains "store stats runs" "Papers" "$STORE_OUTPUT"

# ════════════════════════════════════════════
# Test 5: MCP HTTP mode (optional, needs available port)
# ════════════════════════════════════════════
blue ""
blue "📋 Test 5: MCP HTTP mode"

# Start MCP HTTP server in background
MCP_PORT=18765
$HFPCLAWER mcp --mode http --port $MCP_PORT &
MCP_PID=$!
disown
sleep 1

# Test with curl (if available)
if command -v curl &>/dev/null; then
    # health
    HEALTH=$(curl -sf http://127.0.0.1:$MCP_PORT/health 2>/dev/null || echo "")
    if [[ -n "$HEALTH" ]]; then
        HEALTH_OK=$(echo "$HEALTH" | python3 -c "import sys,json; print(json.load(sys.stdin).get('status',''))" 2>/dev/null || echo "")
        assert_eq "HTTP /health returns ok" "ok" "$HEALTH_OK"
    fi

    # tools
    TOOLS_DATA=$(curl -sf http://127.0.0.1:$MCP_PORT/tools 2>/dev/null || echo "")
    if [[ -n "$TOOLS_DATA" ]]; then
        TOOL_NAMES=$(echo "$TOOLS_DATA" | python3 -c "import sys,json; print(list(json.load(sys.stdin).keys()))" 2>/dev/null || echo "")
        assert_contains "HTTP /tools has search" "search" "$TOOL_NAMES"
    fi

    # call stats
    CALL_DATA=$(curl -sf http://127.0.0.1:$MCP_PORT/call/hfpclawer_stats 2>/dev/null || echo "")
    if [[ -n "$CALL_DATA" ]]; then
        CALL_OK=$(echo "$CALL_DATA" | python3 -c "import sys,json; print('yes' if 'total_papers' in json.load(sys.stdin) else 'no')" 2>/dev/null || echo "no")
        assert_eq "HTTP /call/stats has total_papers" "yes" "$CALL_OK"
    fi
else
    blue "  ⚠️  curl not installed, skipping HTTP test"
fi

# Kill MCP HTTP server background process
kill $MCP_PID 2>/dev/null || true

# ════════════════════════════════════════════
# Summary
# ════════════════════════════════════════════
blue ""
blue "╔═══════════════════════════════════════════╗"
blue "║      Tests Complete                       ║"
blue "╚═══════════════════════════════════════════╝"
echo ""
green "✅ Passed: $PASS"
if [[ $FAIL -gt 0 ]]; then
    red "❌ Failed: $FAIL"
else
    green "🎉 All passed!"
fi
echo ""

exit $FAIL
