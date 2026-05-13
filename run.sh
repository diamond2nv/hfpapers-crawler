#!/usr/bin/env bash
# run.sh — 一键运行爬虫管道
# 用法: bash run.sh

set -e
cd "$(dirname "$0")"
source venv/bin/activate

DATE=$(date +%Y%m%d_%H%M%S)
LOG_DIR="logs"
mkdir -p "$LOG_DIR"

echo "=========================================="
echo "  HF Papers 深度爬虫 — $DATE"
echo "=========================================="

echo ""
echo "[1/4] Scrapy 爬取论文列表..."
python3 -m scrapy crawl hfpapers \
    -s LOG_FILE="$LOG_DIR/scrapy_$DATE.log" \
    -s LOG_LEVEL=INFO 2>&1 | tail -20

# 检查是否产出了候选列表
CANDIDATE="data/candidates_latest.json"
if [ ! -f "$CANDIDATE" ]; then
    echo "[WARN] 候选列表未生成，尝试查找..."
    ls data/ 2>/dev/null || echo "data/ 为空，爬虫未产出结果"
    # 尝试备用爬取方式
    echo "[FALLBACK] 使用 web_extract + requests 备用方案..."
    python3 fallback_crawl.py 2>&1
fi

echo ""
echo "[2/4] 下载 + 转换 + 代码检 (3 workers)..."
python3 download_arxiv.py "$CANDIDATE" 2>&1 | tee "$LOG_DIR/download_$DATE.log"

echo ""
echo "[3/4] 候选论文摘要..."
python3 analyze_candidates.py 2>&1 | head -30

echo ""
echo "[4/4] 集成到 wiki..."
python3 integrate_wiki.py 2>&1

echo ""
echo "=========================================="
echo "  完成!"
echo "  PDFs:     pdfs/"
echo "  Markdown: mds/"
echo "  去重记录: ~/wiki/raw/papers/hfpapers-crawled.json"
echo "=========================================="
