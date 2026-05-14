#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fix_failed_reason.py -- Fix AsyncPdfDownloader empty error string on failure

In _download_one, the PDF download retry-exhaustion path was setting
error="" in the result dict. This patch captures the actual exception
message and propagates it.
"""

import os

FILEPATH = os.path.expanduser(
    "~/Gitlab/Agentic4Sci/hfpapers-crawler/hfpapers/pdf_downloader_async.py"
)
with open(FILEPATH) as f:
    content = f.read()

# Fix: propagate actual exception when 3 retries exhausted
old = """        self._stats["failed"] += 1
        result = {"arxiv_id": aid, "success": False,
                  "pdf_path": "", "md_path": "", "error": "failed after 3 retries"}"""

new = """        self._stats["failed"] += 1
        error_msg = err_msg if "err_msg" in dir() else "failed after 3 retries"
        result = {"arxiv_id": aid, "success": False,
                  "pdf_path": "", "md_path": "", "error": error_msg}"""

if old in content:
    content = content.replace(old, new)
    # Also fix variable capture in inner retry loop
    old2 = """                except (asyncio.TimeoutError, Exception) as e:
                    if attempt < 2:
                        await asyncio.sleep(2 ** attempt)
                    else:
                        self._stats["failed"] += 1
                        logger.warning(f"  {aid}: {e}")
                        result = {"arxiv_id": aid, "success": False,
                                  "pdf_path": "", "md_path": "", "error": str(e)}"""
    new2 = """                except (asyncio.TimeoutError, Exception) as e:
                    err_msg = str(e)
                    if attempt < 2:
                        await asyncio.sleep(2 ** attempt)
                    else:
                        self._stats["failed"] += 1
                        logger.warning(f"  {aid}: {err_msg}")
                        result = {"arxiv_id": aid, "success": False,
                                  "pdf_path": "", "md_path": "", "error": err_msg}"""
    content = content.replace(old2, new2)

    with open(FILEPATH, "w") as f:
        f.write(content)
    print("Fixed failed_reason propagation bug")
else:
    print("Pattern not found, checking alternative...")
    with open(FILEPATH) as f:
        lines = f.readlines()
    for i, line in enumerate(lines):
        if "failed after 3" in line:
            print(f"Line {i + 1}: {line.rstrip()}")
