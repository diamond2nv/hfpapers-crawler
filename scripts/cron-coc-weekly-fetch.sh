#!/bin/bash
# coc-weekly-fetch.sh — 每周腔光机械 arXiv 采集
SCRIPT_DIR="$HOME/.hermes/scripts"
python3 "$SCRIPT_DIR/multi-repo-arxiv-fetch.py" --days 7 --quiet --domain coc 2>/dev/null
echo "[done]"