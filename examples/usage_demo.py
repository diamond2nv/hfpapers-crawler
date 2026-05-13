#!/usr/bin/env python3
"""
hfpapers-clawler Usage Demo

Installation:
    pip install hfpclawer

Usage:
    python examples/usage_demo.py
"""
import os
import tempfile

print("=" * 60)
print("hfpapers-clawler API Usage Demo")
print("=" * 60)


# ─── 1. Basic Config ─────────────────────────────
from hfpapers.config import get, load_config

# load_config() automatically reads config.yaml from the project root
# Override with _TEST_HFPAPERS_CONFIG env var for tests
cfg = load_config()
print(f"\n1. Config loaded: {len(cfg)} top-level keys")
print(f"   Search query: {cfg.get('search', {}).get('queries', [{'query': 'N/A'}])[0]['query']}")
print(f"   Relevance threshold: {get('classification.threshold_pass')}")


# ─── 2. Paper Store ──────────────────────────
from hfpapers.paper_store import (
    PaperRecord,
    PaperStore,
    ensure_paper,
)

# Use a temporary database
with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
    db_path = f.name

try:
    store = PaperStore(db_path=db_path)

# Add a paper
    rec = PaperRecord(
        title="Fourier Neural Operator for PDEs",
        abstract="Learning PDE solution operators with Fourier transforms in the neural network framework",
        year=2023,
        source="demo",
        relevance=90,
    )
    sf_id = store.upsert_paper(rec)
    store.add_identifier(sf_id, "arxiv", "2010.08895", source="demo")

    print(f"\n2. Paper Store: sf_id={sf_id}")
    print(f"\n2. Paper Store: sf_id={sf_id}")
    print(f"   Paper: {got.title}")
    ids = store.get_identifiers(sf_id)
    for i in ids:
        print(f"   Identifier: {i.id_type}={i.id_value}")


    # ─── 3. Search Papers ─────────────────────────────
    # Add more papers for search testing
    sf2 = store.upsert_paper(PaperRecord(title="DeepONet: Learning Operators", relevance=80))
    store.add_identifier(sf2, "arxiv", "1910.03193")

    papers = store.search_papers("Fourier")
    print(f"\n3. Search 'Fourier': found {len(papers)} papers")
    for p in papers:
        print(f"   [{p.relevance}] {p.title}")


    # ─── 4. Stats ─────────────────────────────────
    stats = store.stats()
    print("\n4. Store stats:")
    print(f"   Total papers: {stats['papers_total']}")
    print(f"   Verified: {stats['papers_verified']}")
    print(f"   Identifiers: {stats['identifiers_total']}")


    # ─── 5. High-level Interface ──────────────────────────
    from hfpapers.paper_store import ensure_paper

    sf_id3, is_new = ensure_paper(
        arxiv_id="2301.11167",
        title="Physics-Informed Neural Networks",
        source="demo",
        relevance=85,
    )
    print(f"\n5. ensure_paper: sf_id={sf_id3} is_new={is_new}")


    # ─── 6. Hardware Probe ─────────────────────────────
    from hfpapers.hardware import HardwareProbe

    hw = HardwareProbe()
    print(f"\n6. Hardware probe: {hw.summary()}")
    print(f"   PDF converter: {'available' if hw.use_pdf_converter else 'unavailable'}")
    print(f"   BERT acceleration: {'available' if hw.use_bert else 'unavailable (needs CUDA)'}")


    # ─── 7. CLI Commands ─────────────────────────────
    from typer.testing import CliRunner

    from hfpapers.cli import app

    runner = CliRunner()
    result = runner.invoke(app, ["config"])
    print(f"\n7. CLI 'hfpclawer config': exit_code={result.exit_code}")


    # ─── 8. MCP Integration ─────────────────────────────
    from hfpapers.mcp_server import MCP_TOOLS
    print(f"\n8. MCP tools ({len(MCP_TOOLS)} available):")
    for name, info in sorted(MCP_TOOLS.items()):
        desc = info.get("description", "")[:60]
        print(f"   {name}: {desc}...")

finally:
    # Cleanup
    if os.path.exists(db_path):
        os.unlink(db_path)
    if os.path.exists(db_path + "-wal"):
        os.unlink(db_path + "-wal")

print(f"\n{'=' * 60}")
print("✅ Demo completed successfully")
print(f"{'=' * 60}")
