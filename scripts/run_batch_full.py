#!/usr/bin/env python3
"""
run_batch_full.py — Iterate batch downloads until all papers are done

Usage:
    python3 scripts/run_batch_full.py [--batch-size 50] [--max-batches 0]
    
Run from project root. Interrupt with Ctrl+C, resuming is safe (resumes from DB state).
"""

import sys
import time
import logging

# Ensure project root is on sys.path
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from hfpapers.download_queue import DownloadQueue

BATCH_SIZE = 50
MAX_BATCHES = 0  # 0 = unlimited


def main():
    import argparse
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
        # 检查还有没有 pending
        counts = queue.count_pending()
        pending = counts.get("pending", 0)
        if pending == 0:
            print(f"\n✅ All done! Total time: {time.time()-start_time:.0f}s")
            break

        if max_batches and batch_num >= max_batches:
            print(f"\n⏹ Reached max batches ({max_batches})")
            break

        batch_num += 1
        print(f"\n{'='*50}")
        print(f"📦 Batch {batch_num} (pending: {pending}, batch_size: {batch_size})")
        print(f"{'='*50}")

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

        print(f"  ⏱ {batch_elapsed:.0f}s | this batch: {summary.summary_line}")
        print(f"  📊 Cumulative: ⬇️{total_dl} 📝{total_conv} 📋{total_wiki} ❌{total_fail}")

        if summary.errors:
            for e in summary.errors[:3]:
                print(f"    ❌ {e}")

        # 如果 pending < batch_size 的 2 倍，缩小批大小避免空循环
        remaining = counts.get("pending", 0) - summary.total
        if remaining < batch_size // 2:
            batch_size = min(batch_size, remaining)

        # 短暂 pause 避免疯狂请求
        if remaining > 0:
            print(f"  📊 Remaining: ~{remaining} papers (~{remaining/50:.0f} batches)")
            time.sleep(1)

    total_elapsed = time.time() - start_time
    print(f"\n{'='*50}")
    print(f"🏁 FULL COMPLETE")
    print(f"  ⏱ {total_elapsed:.0f}s ({total_elapsed/60:.0f}min)")
    print(f"  ⬇️ {total_dl} DL | 📝 {total_conv} MD | 📋 {total_wiki} wiki | ❌ {total_fail} fail")
    print(f"{'='*50}")


if __name__ == "__main__":
    main()
