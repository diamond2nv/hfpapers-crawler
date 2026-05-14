#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""run_batch_full.py -- Iterate batch downloads until all papers are done

Usage:
    python3 scripts/run_batch_full.py [--batch-size 50] [--max-batches 0]

Run from project root. Interrupt with Ctrl+C, resuming is safe (resumes from DB state).
"""

import argparse
import sys
import time
from pathlib import Path

# Ensure project root is on sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from hfpapers.download_queue import DownloadQueue


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--batch-size", type=int, default=50)
    parser.add_argument("--max-batches", type=int, default=0, help="0=unlimited")
    parser.add_argument("--priority", default="P1")
    args = parser.parse_args()

    batch_size = args.batch_size
    max_batches = args.max_batches
    priority = args.priority

    total_dl = 0
    total_conv = 0
    total_wiki = 0
    total_fail = 0
    batch_num = 0
    start_time = time.time()

    queue = DownloadQueue(max_concurrent=8)

    while True:
        counts = queue.count_pending()
        pending = counts.get("pending", 0)
        if pending == 0:
            print(f"\nAll done! Total time: {time.time() - start_time:.0f}s")
            break

        if max_batches and batch_num >= max_batches:
            print(f"\nReached max batches ({max_batches})")
            break

        batch_num += 1
        print(f"\n{'=' * 50}")
        print(f"Batch {batch_num} (pending: {pending}, batch_size: {batch_size})")
        print(f"{'=' * 50}")

        batch_start = time.time()
        summary = queue.batch_download(
            batch_size=batch_size,
            priority=priority,
            skip_convert=False,
            to_wiki=True,
        )
        batch_elapsed = time.time() - batch_start

        total_dl += summary.downloaded
        total_conv += summary.converted
        total_wiki += summary.wiki_synced
        total_fail += summary.failed

        print(f"  {batch_elapsed:.0f}s | this batch: {summary.summary_line}")
        print(f"  Cumulative: DL={total_dl} MD={total_conv} wiki={total_wiki} fail={total_fail}")

        if summary.errors:
            for e in summary.errors[:3]:
                print(f"    FAIL: {e}")

        remaining = counts.get("pending", 0) - summary.total
        if remaining < batch_size // 2:
            batch_size = min(batch_size, remaining)

        if remaining > 0:
            print(f"  Remaining: ~{remaining} papers (~{remaining // 50 + 1} batches)")
            time.sleep(1)

    total_elapsed = time.time() - start_time
    print(f"\n{'=' * 50}")
    print("FULL COMPLETE")
    print(f"  {total_elapsed:.0f}s ({total_elapsed // 60}min)")
    print(f"  DL={total_dl} | MD={total_conv} | wiki={total_wiki} | fail={total_fail}")
    print(f"{'=' * 50}")


if __name__ == "__main__":
    main()
