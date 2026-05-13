#!/usr/bin/env bash
# ─── E2E Install Verification Script ─────────────
# Simulates a third-party user installing hfpclawer:
#   pip install hfpclawer            # Core install
#   pip install hfpclawer[llm]       # +LLM
#   pip install hfpclawer[pdf]       # +PDF conversion
#
# Usage:
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
        red "    ❌ $desc (expected '$expected', got '$actual')"
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
blue "║   hfpclawer E2E Install Verification      ║"
blue "╚═══════════════════════════════════════════╝"

# ════════════════════════════════════════════
# 1: pip install hfpclawer (core)
# ════════════════════════════════════════════
echo ""
blue "📋 1: pip install hfpclawer (core)"

pip install "$PROJECT_DIR" -q 2>&1 | tail -1 || {
    red "    ❌ pip install failed"
    exit 1
}

HELP=$(hfpclawer --help 2>&1 || true)
assert_contains "hfpclawer --help lists search" "search" "$HELP"
assert_contains "hfpclawer --help lists audit" "audit" "$HELP"
assert_contains "hfpclawer --help lists mcp" "mcp" "$HELP"
assert_contains "hfpclawer --help lists store" "store" "$HELP"
assert_contains "hfpclawer --help lists download" "download" "$HELP"

# Core module import
MOD_IMPORT=$(py "
from hfpapers.cli import app; print('cli:ok')
from hfpapers.paper_store import PaperStore; print('store:ok')
from hfpapers.mcp_server import MCP_TOOLS; print(f'mcp:{len(MCP_TOOLS)}')
")
assert_contains "Core modules importable" "cli:ok" "$MOD_IMPORT"
assert_contains "MCP_TOOLS has 7 tools" "mcp:7" "$MOD_IMPORT"

# ════════════════════════════════════════════
# 2: pip install hfpclawer[llm]
# ════════════════════════════════════════════
echo ""
blue "📋 2: pip install hfpclawer[llm] + [pdf]"

pip install "$PROJECT_DIR[llm,pdf]" -q 2>&1 | tail -1 || {
    yellow "    ⚠️  [llm,pdf] installation may be incomplete"
    ((FAIL++))
}

LLM_OK=$(py "from litellm import completion; print('ok')")
assert_contains "litellm importable" "ok" "$LLM_OK"

PDF_OK=$(py "import pymupdf4llm; print('ok')")
assert_contains "pymupdf4llm importable" "ok" "$PDF_OK"

# ════════════════════════════════════════════
# 3: CLI offline subcommands
# ════════════════════════════════════════════
echo ""
blue "📋 3: CLI offline subcommands"

OUT=$(hfpclawer audit 2>&1 | head -5 || true)
assert_contains "audit is runnable" "Audit" "$OUT"

OUT=$(hfpclawer store stats 2>&1 | head -5 || true)
assert_contains "store stats is runnable" "Paper Store" "$OUT"

OUT=$(hfpclawer config 2>&1 || true)
assert_contains "config is runnable" "search" "$OUT"

OUT=$(hfpclawer store export xlsx 2>&1 || true)
assert_contains "store export errors" "not supported" "$OUT"

OUT=$(hfpclawer dedup 2>&1 || true)
assert_contains "dedup is runnable" "Dedup" "$OUT"

# ════════════════════════════════════════════
# 4: MCP stdio protocol verification
# ════════════════════════════════════════════
echo ""
blue "📋 4: MCP stdio protocol verification"

MCP_OUT=$(echo '{"jsonrpc":"2.0","id":1,"method":"initialize"}
{"jsonrpc":"2.0","id":2,"method":"tools/list"}' | hfpclawer mcp 2>/dev/null || true)

LINE_CNT=$(echo "$MCP_OUT" | grep -c . || true)
if [[ "$LINE_CNT" -ge 2 ]]; then
    green "    ✅ MCP stdio returned $LINE_CNT response lines"
    ((PASS++))

    TOOL_CNT=$(echo "$MCP_OUT" | tail -1 | python3 -c "
import sys, json
try:
    r = json.load(sys.stdin)
    print(len(r['result']['tools']))
except: print(0)
" 2>/dev/null || echo "0")
    assert_eq "tools/list returns 7 tools" "7" "$TOOL_CNT"
else
    red "    ❌ MCP stdio returned ${LINE_CNT:-0} lines (expected ≥2)"
    echo "    OUTPUT: $(echo "$MCP_OUT" | head -5)"
    ((FAIL++))
fi

# ════════════════════════════════════════════
# Summary
# ════════════════════════════════════════════
echo ""
blue "╔═══════════════════════════════════════════╗"
blue "║      Installation Verification Complete    ║"
blue "╚═══════════════════════════════════════════╝"
echo ""
green "✅ Passed: $PASS"
if [[ $FAIL -gt 0 ]]; then
    red "❌ Failed: $FAIL"
    exit 1
else
    green "🎉 All passed!"
    echo ""
    echo "  Recommended third-party installation:"
    echo "    pip install hfpclawer                 # Core"
    echo "    pip install 'hfpclawer[llm,pdf]'      # Core + LLM + PDF"
    echo ""
fi
