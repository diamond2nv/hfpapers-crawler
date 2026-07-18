#!/bin/bash
# gsnv-weekly-fetch.sh — 每周钢轨NV检测 arXiv 采集
SCRIPT_DIR="$HOME/.hermes/scripts"
python3 "$SCRIPT_DIR/multi-repo-arxiv-fetch.py" --days 7 --quiet --domain gsnv 2>/dev/null
echo "[done]"