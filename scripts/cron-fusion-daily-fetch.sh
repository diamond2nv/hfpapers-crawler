#!/bin/bash
# fusion-daily-fetch.sh — 每日核聚变arXiv采集，带重试 (TEMPLATE)
# Customize SCRIPT_DIR and DATA_DIR for your Hermes setup
SCRIPT_DIR="${HERMES_SCRIPTS_DIR:-$HOME/.hermes/scripts}"
DATA_DIR="${HFPCLAWER_DATA_DIR:-$HOME/.hermes/data/arxiv-live}"

MAX_ATTEMPTS=2
ATTEMPT=0
FETCH_OK=0

while [ $ATTEMPT -lt $MAX_ATTEMPTS ]; do
    ATTEMPT=$((ATTEMPT + 1))
    if python3 "$SCRIPT_DIR/multi-repo-arxiv-fetch.py" --days 7 --quiet --domain fusion 2>/dev/null; then
        FETCH_OK=1
        break
    fi
    echo "[WARN] fetch attempt $ATTEMPT failed, retrying..." >&2
    sleep 5
done

if [ "$FETCH_OK" -eq 1 ]; then
    python3 "$SCRIPT_DIR/arxiv-live-to-hfpclawer.py" --quiet 2>/dev/null
    echo "[done]"
else
    echo "FAILED: all $MAX_ATTEMPTS attempts exhausted" >&2
    exit 1
fi
