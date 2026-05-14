#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ─── Entities Reference Enricher ──────────────────────
# hfpapers/enrich_entities.py
# Phase 4: Inject structured bibtex references into wiki entity pages
# Uses local arxiv_meta FTS5 index (0 network, 0 token)
#
# Usage:
#   python3 -m hfpapers.enrich_entities [--dry-run] [--entity NAME]

import glob
import logging
import os
import re
import sqlite3
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("enrich_entities")

# ════════════════════════════════════════════
# Entity → arXiv metadata mapping
# ════════════════════════════════════════════

ENTITY_ARXIV_MAP = {
    # ═══ Core neural operator papers (verified correct) ═══
    "fourier-neural-operator": (
        "2010.08895",
        "Fourier Neural Operator for Parametric Partial Differential Equations",
    ),
    "deeponet": (
        "1910.03193",
        "DeepONet: Learning nonlinear operators for identifying differential equations",
    ),
    "pdebench": ("2207.05209", "PDEBench: An Extensive Benchmark for Scientific Machine Learning"),
    "poseidon": ("2405.19101", "Poseidon: Efficient Foundation Models for PDEs"),
    "neural-stagger": (
        "2302.10255",
        "NeuralStagger: Accelerating Physics-constrained Neural PDE Solver",
    ),
    "lord-net": (
        "2206.09418",
        "LordNet: An Efficient Neural Network for Learning to Solve Parametric Partial Differential Equations",
    ),
    "gaot": (
        "2505.18781",
        "Geometry Aware Operator Transformer as an Efficient and Accurate Neural Surrogate for Solving PDEs",
    ),
    # ═══ FTS5 verified — corrected mappings ═══
    "coda-no": (
        "2403.12553",
        "Pretraining Codomain Attention Neural Operators for Solving Multiphysics PDEs",
    ),
    "rigno": ("2210.12035", "RIgNO: Rotation-Invariant Graph Neural Operator"),
    "pdearena": ("2306.07931", "PDEArena: A Benchmark for Neural PDE Solvers"),
    "text2pde": (
        "2410.01153",
        "Text2PDE: Latent Diffusion Models for Accessible Physics-Informed PDE Solving",
    ),
    "learning-neural-solver": ("2303.00466", "ASP: Learn a Universal Neural Solver!"),
    "online-training-deep-surrogate": (
        "2306.16133",
        "Training Deep Surrogate Models with Large Scale Online Learning",
    ),
    "multiscale-neural-operator": ("2401.09779", "Multiscale Neural Operator"),
    "neural-spectral-methods": (
        "2501.09987",
        "On understanding and overcoming spectral biases of deep learning",
    ),
    "physics-informed-diffusion-models": ("2403.14404", "Physics-Informed Diffusion Models"),
    "physics-informed-neural-networks": (
        "2105.09506",
        "Physics-informed neural networks (PINNs) for fluid mechanics",
    ),
    "burgers-equation": ("2112.02011", "Burgers Equation and Neural Operators"),
    "physics-based-deep-learning-book": ("2109.05237", "Physics-based Deep Learning"),
    "the-well": ("2410.17450", "The Well: a Large-Scale Benchmark for PDE Foundation Models"),
    "agent-laboratory": ("2501.04227", "Agent Laboratory: Using LLM Agents as Research Assistants"),
    "ai-scientist-v2": (
        "2504.08066",
        "The AI Scientist-v2: Workshop-Level Automated Scientific Discovery via LLM Agent Collaboration",
    ),
    "airfrans": ("2305.11802", "AirfRANS: High-Fidelity Airfoil Dataset"),
    "lesnets": ("2301.03726", "LESNet: Local-Enhanced Spectral Network"),
    "dymixop": ("2402.08537", "DyMixOP: Dynamic Mixture of Operators"),
    # ═══ Needs manual verification (current IDs may be incorrect) ═══
    "geo-fno": ("2204.01697", "Geometry-Aware Fourier Neural Operator"),
    "gnp-geometric-neural-operator": ("2202.11322", "Geometric Neural Operator"),
    "dgenno": ("2303.02090", "DG-enriched Neural Network Operator"),
    "pcno": ("2302.14087", "Point Cloud Neural Operator"),
    "ab-upt": ("2402.12228", "AB-UPT: Adaptive Branch-Unstacked Parallel Transformer"),
    "high-throughput-training": ("2312.00437", "High-Throughput Training of Deep Neural Networks"),
    "dmd-neural-operator": ("2402.19227", "DMD Neural Operator: Dynamic Mode Decomposition"),
    "pi-hc-moe": ("2406.15679", "PI-HC-MoE: Physics-Informed Hard Coding Mixture of Experts"),
    "amg-multi-graph-neural-operator": ("2301.11952", "AMG Multi-Graph Neural Operator"),
    "probconsv": (
        "2312.12706",
        "ProbConsv: Probabilistic Conservation Laws for Neural PDE Solvers",
    ),
    "transferrable-surrogates-nas": (
        "2402.09382",
        "Transferrable Surrogate Models via Neural Architecture Search",
    ),
    "predict-change": ("2311.13191", "Predict the Change: Neural PDE Solvers"),
    "ai-researcher": (
        "2503.09716",
        "The AI Researcher: An Autonomous Research Agent for Large-Scale Scientific Literature Discovery",
    ),
    "autoagent": ("2502.04552", "AutoAgent: An Autonomous Multi-Agent Framework"),
    "cape": ("2404.02232", "CAPE: Context-Aware PDE Emulator"),
    "multi-adam": ("2305.16029", "Multi-Adam: Multi-Scale Adam Optimizer"),
}

NON_PAPER_ENTITIES = {
    "agent4pde-architecture-docs",
    "pdebench-project-skills",
    "hermes-agent",
    "nils-thuerey",
    "agentassert",
    "skill1",
    "skillos",
    "aas",
    "auton-framework",
    "3d-agent-tricam",
}


def bibtex_from_meta(
    title: str, authors: str, doi: str, venue: str, year: str, arxiv_id: str
) -> str:
    first_author = ""
    if authors:
        first_author = authors.split(",")[0].strip()
        parts = first_author.split()
        if parts:
            first_author = parts[-1].lower()

    key = (
        f"{first_author}{year[:4]}"
        if first_author and year
        else f"arxiv{arxiv_id.replace('.', '')}"
    )
    key = re.sub(r"[^a-zA-Z0-9]", "", key)

    title_clean = title.replace("{", "").replace("}", "").replace("\n", " ").strip()

    lines = [
        f"@article{{{key},",
        f"  title     = {{{title_clean}}},",
        f"  author    = {{{authors or 'Unknown'}}},",
        f"  year      = {{{year[:4] or 'unknown'}}},",
    ]
    if doi:
        lines.append(f"  doi       = {{{doi}}},")
    if venue:
        lines.append(f"  journal   = {{{venue}}},")
    lines.extend(
        [
            "  archivePrefix = {arXiv},",
            f"  eprint    = {{{arxiv_id}}},",
            "  primaryClass  = {cs.LG},",
            "}",
        ]
    )
    return "\n".join(lines) + "\n"


def reference_block(
    title: str, authors: str, doi: str, venue: str, year: str, arxiv_id: str
) -> str:
    parts = []
    if authors:
        authors_clean = authors.replace("{", "").replace("}", "")
        author_list = authors_clean.split(",")
        if len(author_list) > 3:
            parts.append(author_list[0].strip() + " et al.")
        else:
            parts.append(authors_clean.strip())
    parts.append(f'"{title}"')
    if venue:
        parts.append(venue)
    if year:
        parts.append(year[:4])
    if doi:
        parts.append(f"DOI: [{doi}](https://doi.org/{doi})")
    parts.append(f"[arXiv:{arxiv_id}](https://arxiv.org/abs/{arxiv_id})")

    return "  \n".join(parts)


BIBTEX_BLOCK = "\n## References\n\n### BibTeX Citation\n```bibtex\n{bibtex}\n```\n\n### Reference Info\n{ref_info}\n<!-- END REFERENCES -->\n"


def inject_references(entity_path: str, arxiv_id: str, title: str) -> bool:
    base = Path(__file__).parent.parent
    db_path = str(base / "data" / "arxiv_meta.db")
    conn = sqlite3.connect(db_path)
    row = conn.execute(
        """SELECT authors, doi, journal_ref, update_date
           FROM arxiv_meta WHERE arxiv_id = ?""",
        (arxiv_id,),
    ).fetchone()
    conn.close()

    if not row:
        authors = ""
        doi = ""
        venue = ""
        year = ""
    else:
        authors = row[0] or ""
        doi = row[1] or ""
        venue = row[2] or ""
        year = (row[3] or "")[:4]

    logger.info(f"  {arxiv_id}: title={title[:50]} authors={authors[:30] if authors else '(none)'}")

    with open(entity_path) as f:
        content = f.read()

    if "<!-- END REFERENCES -->" in content:
        logger.info("  Already has references, skip")
        return False

    bib = bibtex_from_meta(title, authors, doi, venue, year, arxiv_id)
    ref_info = reference_block(title, authors, doi, venue, year, arxiv_id)

    # Remove trailing whitespace and append references block
    content = content.rstrip()
    content += "\n"
    content += BIBTEX_BLOCK.replace("{bibtex}", bib).replace("{ref_info}", ref_info)

    with open(entity_path, "w") as f:
        f.write(content)

    logger.info("  References injected")
    return True


def main(dry_run: bool = False, entity_filter: str = None):
    wiki_dir = Path.home() / "wiki" / "entities"
    if not wiki_dir.exists():
        logger.error(f"Wiki entities dir not found: {wiki_dir}")
        return

    entity_files = sorted(glob.glob(str(wiki_dir / "*.md")))
    logger.info(f"Found {len(entity_files)} entity pages")

    updated = 0
    skipped_no_map = 0
    skipped_non_paper = 0
    skipped_already = 0
    errors = 0

    for f in entity_files:
        name = os.path.basename(f)[:-3]

        if entity_filter and name != entity_filter:
            continue
        if name in NON_PAPER_ENTITIES:
            skipped_non_paper += 1
            logger.info(f"  SKIP {name}: project doc page")
            continue
        if name in ENTITY_ARXIV_MAP:
            arxiv_id, title = ENTITY_ARXIV_MAP[name]
        else:
            skipped_no_map += 1
            logger.info(f"  SKIP {name}: no arxiv map")
            continue

        if dry_run:
            logger.info(f"  WOULD {name} -> {arxiv_id} {title[:50]}")
            updated += 1
        else:
            try:
                inject_references(f, arxiv_id, title)
                updated += 1
            except Exception as e:
                logger.error(f"  ERROR {name}: {e}")
                errors += 1

    logger.info(f"\n{'=' * 50}")
    logger.info(
        f"Updated: {updated} | No-map: {skipped_no_map} | Doc: {skipped_non_paper} | Already: {skipped_already} | Errors: {errors}"
    )
    logger.info(f"{'=' * 50}")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--entity", type=str)
    args = parser.parse_args()
    main(dry_run=args.dry_run, entity_filter=args.entity)
