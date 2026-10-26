#!/usr/bin/env python3
"""
SUPERSEDED by `scripts/cron_round.py` (v0.19.14) -- kept as the provenance record for this
round: the round-level work is now a reusable runner (axis query -> normalised store diff ->
ingest -> dedup regression). Do not copy the one-shot pattern below: it carried its own
metadata, its own idea of "already filed", and (in the 10-10 case) its own HTTP client.
2026-10-10 自主循环 round10：3 篇「AI for Science + Agent 验证层」论文入库。

纪律：真库直连 hfpapers-crawler/data/papers.db（HFPAPERS_DATA_DIR 必须显式指本仓 data，
否则默认 state root 落空报 0 篇）；skip_crossref=True 防 Crossref 低置信污染；
source/imported_via='cron-2026-10-10-round10'。零 LLM 参与解析（arXiv API 机械层直取）。

采集口径（本轮）：monitor 的 `all:"AI agent" AND all:verification`（max_results=5）
top-5 与 10-09 **完全相同 ⇒ 零新增**（cron diff 由「有输出」变「空输出」即此因）。
故换轴：① `all:"AI for science" AND all:agent`（submittedDate desc）
       ② `all:"scientific discovery" AND all:"agent"`（submittedDate desc）
       ③ `all:"AI for science" AND all:verification`（submittedDate desc）
从三轴未入库件中选取与本方向 gap（「可判定、可迁移的声明级判据」）最相关的 3 篇。
"""
from __future__ import annotations

import re
import ssl
import urllib.request

from hfpapers.paper_store import ensure_paper, store_stats  # type: ignore[import-not-found]

SOURCE = "cron-2026-10-10-round10"
IDS = ["2610.06986", "2609.37603", "2610.05197"]


def fetch(ids: list[str]) -> list[dict]:
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    url = ("https://export.arxiv.org/api/query?id_list=" + ",".join(ids)
           + "&max_results=10")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (research)"})
    with urllib.request.urlopen(req, context=ctx, timeout=30) as r:
        xml = r.read().decode("utf-8", "ignore")
    out = []
    for e in re.findall(r"<entry>(.*?)</entry>", xml, re.S):
        def g(t, _e=e):
            m = re.search(r"<" + t + r"[^>]*>(.*?)</" + t + r">", _e, re.S)
            return re.sub(r"\s+", " ", m.group(1)).strip() if m else ""
        aid = re.search(r"<id>http://arxiv.org/abs/([^<]+)</id>", e)
        out.append({
            "arxiv_id": aid.group(1) if aid else "",
            "title": g("title"),
            "abstract": g("summary"),
            "published": g("published"),
        })
    return out


def main() -> int:
    print("BEFORE stats:", store_stats())
    rows = fetch(IDS)
    assert len(rows) == len(IDS), f"fetched {len(rows)} != {len(IDS)}"
    for p in rows:
        sf, is_new = ensure_paper(
            p["arxiv_id"], title=p["title"], abstract=p["abstract"],
            source=SOURCE, skip_crossref=True, imported_via=SOURCE,
        )
        print(f"ENSURE {p['arxiv_id']} sf_id={sf} is_new={is_new} "
              f"pub={p['published']} title={p['title'][:70]}")
    print("AFTER stats:", store_stats())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
