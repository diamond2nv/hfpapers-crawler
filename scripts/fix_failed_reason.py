#!/usr/bin/env python3
"""
fix_failed_reason.py — 修复 AsyncPdfDownloader 失败时 error="" 的 bug
在 _download_one 中，PDF 下载失败时未把异常信息传入 result dict。
"""

import os, re

# 找到 async downloader 的失败分支
filepath = os.path.expanduser("~/Gitlab/Agentic4Sci/hfpapers-crawler/hfpapers/pdf_downloader_async.py")
with open(filepath) as f:
    content = f.read()

# 修复: 3次重试耗尽时 error="" → 传入实际异常
old = '''        self._stats["failed"] += 1
        result = {"arxiv_id": aid, "success": False,
                  "pdf_path": "", "md_path": "", "error": "failed after 3 retries"}'''

new = '''        self._stats["failed"] += 1
        error_msg = err_msg if "err_msg" in dir() else "failed after 3 retries"
        result = {"arxiv_id": aid, "success": False,
                  "pdf_path": "", "md_path": "", "error": error_msg}'''

if old in content:
    content = content.replace(old, new)
    # 同时修复内层循环中的变量传递
    old2 = '''                except (asyncio.TimeoutError, Exception) as e:
                    if attempt < 2:
                        await asyncio.sleep(2 ** attempt)
                    else:
                        self._stats["failed"] += 1
                        logger.warning(f"  ❌ {aid}: {e}")
                        result = {"arxiv_id": aid, "success": False,
                                  "pdf_path": "", "md_path": "", "error": str(e)}'''
    new2 = '''                except (asyncio.TimeoutError, Exception) as e:
                    err_msg = str(e)
                    if attempt < 2:
                        await asyncio.sleep(2 ** attempt)
                    else:
                        self._stats["failed"] += 1
                        logger.warning(f"  ❌ {aid}: {err_msg}")
                        result = {"arxiv_id": aid, "success": False,
                                  "pdf_path": "", "md_path": "", "error": err_msg}'''
    content = content.replace(old2, new2)
    
    with open(filepath, "w") as f:
        f.write(content)
    print("✅ Fixed failed_reason propagation bug")
else:
    print("⚠️ Pattern not found, checking alternative...")
    # 看看实际内容
    with open(filepath) as f:
        lines = f.readlines()
    for i, l in enumerate(lines):
        if 'failed after 3' in l:
            print(f"Line {i+1}: {l.rstrip()}")
