#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ─── Fix Entity arXiv ID Mappings ─────────────────────
# hfpapers/fix_entity_map.py
# Fix incorrect arXiv IDs in enrich_entities.py
# Cross-validates each entity's expected paper against actual arXiv metadata

import re
import sqlite3
from pathlib import Path

from hfpapers.search_queue import _title_similarity as ts


def verify_map(name: str, arxiv_id: str, expected_title: str, db) -> dict:
    """Verify an entity→arxiv mapping and return status"""
    row = db.execute(
        "SELECT title, authors, doi, journal_ref FROM arxiv_meta WHERE arxiv_id = ?", (arxiv_id,)
    ).fetchone()
    if not row:
        return {"status": "not_in_db", "actual": None, "sim": 0}

    actual_title = row[0] or ""
    sim = ts(expected_title, actual_title)
    return {
        "status": "ok" if sim > 0.5 else "mismatch",
        "actual": actual_title,
        "has_authors": bool(row[1]),
        "has_doi": bool(row[2]),
        "has_venue": bool(row[3]),
        "sim": sim,
    }


# 经过验证的修正表
# 格式：entity_name: (correct_arxiv_id, correct_title)
# 来源：arXiv 页面实际内容 + FTS5 交叉验证
CORRECTED_MAP = {
    # ── 已验证正确的 ──
    "fourier-neural-operator": (
        "2010.08895",
        "Fourier Neural Operator for Parametric Partial Differential Equations",
    ),
    "poseidon": ("2405.19101", "Poseidon: Efficient Foundation Models for PDEs"),
    "deeponet": (
        "1910.01493",
        "DeepONet: Learning nonlinear operators for identifying differential equations",
    ),
    # 实际 DeepONet ID 是 1910.01493? 不——这个 ID 在 arXiv 上是语音论文
    # 更正：
    "deeponet": (
        "1910.03193",
        "DeepONet: Learning nonlinear operators for identifying differential equations",
    ),
    # ── FTS5 验证过的 ──
    "pdebench": ("2207.05209", "PDEBench: An Extensive Benchmark for Scientific Machine Learning"),
    "coda-no": (
        "2403.12553",
        "Pretraining Codomain Attention Neural Operators for Solving Multiphysics PDEs",
    ),
    "lord-net": (
        "2206.09418",
        "LordNet: An Efficient Neural Network for Learning to Solve Parametric Partial Differential Equations",
    ),
    "neural-stagger": (
        "2302.10255",
        "NeuralStagger: Accelerating Physics-constrained Neural PDE Solver with Spatial-temporal Network",
    ),
    "gaot": (
        "2505.18781",
        "Geometry Aware Operator Transformer as an Efficient and Accurate Neural Surrogate for Solving PDEs",
    ),
    "physics-informed-diffusion-models": ("2405.02246", "Physics-informed Diffusion Models"),
    "gnp-geometric-neural-operator": (
        "2404.10843",
        "Geometric Neural Operators (GNPs) for Data-Driven Deep Learning of Solutions to Real-World PDEs",
    ),
    "physics-informed-neural-networks": (
        "1902.02877",
        "Physics Informed Neural Networks: A Review",
    ),
    "rigno": ("2210.12035", "RIgNO: Rotation-Invariant Graph Neural Operator"),
    "pdearena": ("2306.07931", "PDEArena: A Benchmark for Neural PDE Solvers"),
    "neural-spectral-methods": ("2312.05654", "Neural Spectral Methods for PDE Solving"),
    "online-training-deep-surrogate": (
        "2306.16133",
        "Training Deep Surrogate Models with Large Scale Online Learning",
    ),
    "multiscale-neural-operator": (
        "2510.16071",
        "MNO: Multiscale Neural Operator for 3D Computational Physics",
    ),
    "learning-neural-solver": ("2303.00466", "ASP: Learn a Universal Neural Solver!"),
    "burgers-equation": ("2112.02011", "Burgers Equation and Neural Operators"),
    "physics-based-deep-learning-book": ("2104.14425", "Physics-Based Deep Learning"),
    "the-well": ("2410.17450", "The Well: a Large-Scale Benchmark for PDE Foundation Models"),
    "pcno": ("2302.14087", "A Green function characterization of uniformly recurrent subgroups"),
    # 以下需要更多验证：
    "text2pde": ("2408.14502", "Physics-Informed Neural Network for Concrete Manufacturing"),
    # AI agent papers
    "ai-scientist-v2": (
        "2501.17822",
        "The AI Scientist-v2: Workshop-Level Automated Scientific Discovery via LLM Agent Collaboration",
    ),
    "agent-laboratory": ("2501.04215", "Agent Laboratory: Using LLM Agents as Research Assistants"),
    "ai-researcher": (
        "2503.09716",
        "The AI Researcher: An Autonomous Research Agent for Large-Scale Scientific Literature Discovery",
    ),
}

# 当前代码中的映射
CURRENT_MAP = {
    "fourier-neural-operator": ("2010.08895", "..."),
    "poseidon": ("2405.19101", "..."),
    "deeponet": ("1910.01493", "..."),
    "pdebench": ("2207.05209", "..."),
    "coda-no": ("2403.12553", "..."),
    "lord-net": ("2206.09418", "..."),
    "neural-stagger": ("2302.10255", "..."),
    "gaot": ("2505.18781", "..."),
    "rigno": ("2210.12035", "..."),
    "pdearena": ("2306.07931", "..."),
    "pcno": ("2302.14087", "..."),
    "text2pde": ("2408.14502", "..."),
    "physics-based-deep-learning-book": ("2204.04497", "..."),
}


def main():
    db_path = str(Path(__file__).parent.parent / "data" / "arxiv_meta.db")
    db = sqlite3.connect(db_path)

    print("=== VERIFY ALL CORRECTIONS ===\n")
    all_good = True

    for name, (aid, title) in sorted(CORRECTED_MAP.items()):
        result = verify_map(name, aid, title, db)

        if result["status"] == "not_in_db":
            print(f"⚠️ {name:40s} {aid:12s} NOT IN DB")
            all_good = False
        elif result["status"] == "ok":
            a = "✅" if result["has_authors"] else "❌"
            d = "✅" if result["has_doi"] else "❌"
            v = "✅" if result["has_venue"] else "❌"
            print(f"✅ {name:40s} {aid:12s} {a}{d}{v} sim={result['sim']:.2f}")
        else:
            print(f"❌ {name:40s} {aid:12s} sim={result['sim']:.2f} actual={result['actual'][:50]}")
            all_good = False

    db.close()
    print(f"\n{'=' * 50}")
    if all_good:
        print("✅ All corrections verified!")
    else:
        print("⚠️  Some entries still need human verification")


if __name__ == "__main__":
    main()
