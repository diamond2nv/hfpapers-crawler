"""
SUPERSEDED by `scripts/cron_round.py` (v0.19.14) -- kept as the provenance record for this
round: the round-level work is now a reusable runner (axis query -> normalised store diff ->
ingest -> dedup regression). Do not copy the one-shot pattern below: it carried its own
metadata, its own idea of "already filed", and (in the 10-10 case) its own HTTP client.
Round-9 cron ingest: two new arXiv items from the monitor delta (2026-10-09).

Source: monitor `all:"AI agent" AND all:verification` top delta ids
  2610.11177v1 / 2610.10858v1 / 2610.06614v1
2610.06614 (FREA) is already filed (round 10-06) -> dedup regression check.
Metadata taken from arXiv /abs pages (verified via web_extract this run).
"""
import os
import sys

os.environ.setdefault("HFPAPERS_DATA_DIR", os.path.join(os.getcwd(), "data"))
sys.path.insert(0, os.getcwd())

from hfpapers.paper_store import ensure_paper  # noqa: E402

ITEMS = [
    {
        "arxiv_id": "2610.11177v1",
        "title": "Dynamic Mechanism and Information Design in AI-Agent Environments: A General Analytical Framework",
        "source": "arxiv",
        "venue": "arXiv (econ.TH, preprint)",
        "imported_via": "cron-2026-10-09-monitor-delta",
        "abstract": (
            "Develops a general framework for dynamic mechanism and information design with AI agents, "
            "encompassing optimal contracting and integrating evolving hidden information and hidden action "
            "with partial verification, technological authorization, and multi-agent interaction. Establishes "
            "a dynamic revelation principle and a recursive characterization of implementability in which "
            "truthful reporting and post-report obedience are jointly determined through continuation "
            "incentives. In quasilinear optimal-contracting environments, dynamic envelope and "
            "integral-monotonicity methods yield a verification-adjusted dynamic virtual-surplus "
            "representation and identify three margins: dynamic information rents, verification rents, and "
            "the implementation cost of hidden action. Also studies joint design of monitoring, information "
            "use and incentives: more informative monitoring expands the designer's opportunity set, but full "
            "disclosure need not be optimal, and information use can itself alter hidden-action incentives."
        ),
    },
    {
        "arxiv_id": "2610.10858v1",
        "title": "RFChipAgent: Multi-Agentic AI Flow for Analog/RF Chip Design",
        "source": "arxiv",
        "venue": "arXiv (preprint)",
        "imported_via": "cron-2026-10-09-monitor-delta",
        "abstract": (
            "Introduces a first-of-its-kind multi-agentic AI flow RFChipAgent for end-to-end design "
            "automation of Analog/RF circuits, in which autonomous AI agents collaboratively orchestrate the "
            "complete design flow under human supervision. Four pillars: (1) multimodal RAG subsystem with "
            "private per-document FAISS indexing; (2) topology agent plus schematic and testbench agent; "
            "(3) closed-loop hybrid sizing engine combining TPE and CMA-ES, evaluating every candidate in a "
            "simulator-in-the-loop framework; (4) trust-scored simulation database that accumulates verified "
            "performance data and builds an adaptive optimization model. Validated on GF22FDSOI 60 GHz "
            "wideband LNA topologies, showing reductions in design effort while maintaining signoff-quality "
            "verification."
        ),
    },
    # dedup regression: already filed on 10-06 (FREA)
    {"arxiv_id": "2610.06614v1", "title": "", "source": "arxiv", "imported_via": "dedup-regression"},
]

for it in ITEMS:
    sf_id, is_new = ensure_paper(
        arxiv_id=it["arxiv_id"],
        title=it.get("title", ""),
        source=it.get("source", "arxiv"),
        abstract=it.get("abstract", ""),
        venue=it.get("venue", ""),
        skip_crossref=True,
        imported_via=it.get("imported_via", ""),
    )
    print(f"{it['arxiv_id']:>16}  sf_id={sf_id}  is_new={is_new}")
