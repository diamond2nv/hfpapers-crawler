#!/usr/bin/env bash
# run.sh — One-click crawl pipeline runner
# Usage: bash run.sh

set -e
cd "$(dirname "$0")"
source venv/bin/activate

DATE=$(date +%Y%m%d_%H%M%S)
LOG_DIR="logs"
mkdir -p "$LOG_DIR"

echo "=========================================="
echo "  HF Papers Deep Crawl — $DATE"
echo "=========================================="

echo ""
echo "[1/4] Scrapy crawl paper list..."
python3 -m scrapy crawl hfpapers \
    -s LOG_FILE="$LOG_DIR/scrapy_$DATE.log" \
    -s LOG_LEVEL=INFO 2>&1 | tail -20

# Check if candidate list was produced
CANDIDATE="data/candidates_latest.json"
if [ ! -f "$CANDIDATE" ]; then
    echo "[WARN] Candidate list not generated, trying to locate..."
    ls data/ 2>/dev/null || echo "data/ is empty, crawler produced no results"
    # Attempt fallback crawl approach
    echo "[FALLBACK] Using web_extract + requests fallback..."
    python3 fallback_crawl.py 2>&1
fi

echo ""
echo "[2/4] Download + Convert + Code Check (3 workers)..."
python3 download_arxiv.py "$CANDIDATE" 2>&1 | tee "$LOG_DIR/download_$DATE.log"

echo ""
echo "[3/4] Candidate paper summaries..."
python3 analyze_candidates.py 2>&1 | head -30

echo ""
echo "[4/4] Integrate into wiki..."
python3 integrate_wiki.py 2>&1

echo ""
echo "=========================================="
echo "  Complete!"
echo "  PDFs:     pdfs/"
echo "  Markdown: mds/"
echo "  Dedup record: ~/wiki/raw/papers/hfpapers-crawled.json"
echo "=========================================="
