#!/bin/bash
# neural-pde-weekly-fetch.sh — 每周神经算子PDE arXiv 采集
SCRIPT_DIR="$HOME/.hermes/scripts"
python3 "$SCRIPT_DIR/multi-repo-arxiv-fetch.py" --days 7 --quiet --domain neural-pde 2>/dev/null
echo "[done]"