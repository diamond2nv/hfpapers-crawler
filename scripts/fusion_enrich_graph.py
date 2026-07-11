#!/usr/bin/env python3
"""Enrich graph with fusion papers from Chinese institutions via arXiv API.

Adds paper, person nodes and AFFILIATED_WITH edges so Chinese fusion
institutions appear with colored dots on the community map.
"""

from __future__ import annotations

import logging
import pickle
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

import networkx as nx

from hfpapers.graph.schema import EdgeType, NodeType, node_id, paper_node_id, person_node_id
from hfpapers.graph.sources.institutions import institution_abbrev

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("fusion_enrich")

NS = {"a": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}

# Chinese institutions we want to populate — institution_id → list of affiliation keywords
TARGET_INSTS = {
    "institution:southwestern-institute-of-physics": [
        "southwestern institute of physics", "swip", "核工业西南物理研究院",
    ],
    "institution:huazhong-university-of-science-and-technology": [
        "huazhong university", "hust", "华中科技大学",
    ],
    "institution:dalian-university-of-technology": [
        "dalian university of technology", "dut", "大连理工大学",
    ],
    "institution:shanghai-jiao-tong-university": [
        "shanghai jiao tong university", "sjtu", "上海交通大学",
    ],
    "institution:southeast-university": [
        "southeast university", "seu", "东南大学",
    ],
    "institution:soochow-university": [
        "soochow university", "suzhou university", "苏州大学",
    ],
    "institution:peking-university": [
        "peking university", "pku", "北京大学",
    ],
    "asipp": [
        "institute of plasma physics", "asipp", "等离子体物理研究所",
        "chinese academy of sciences",
    ],
    "massachusetts-institute-of-technology": [
        "massachusetts institute of technology", "mit",
    ],
    "commonwealth-fusion-systems": [
        "commonwealth fusion systems", "cfs",
    ],
}

# Fusion search queries (keyword-based, will filter by affiliation)
FUSION_QUERIES = [
    "HL-2A OR HL-2M tokamak",
    "EAST tokamak",
    "J-TEXT tokamak",
    "CFETR fusion",
    "stellarator AND China",
    "tokamak AND China AND plasma",
    "magnetic fusion AND China",
    "plasma confinement AND China",
]


def _arxiv_search(query: str, max_results: int = 20) -> list[tuple[str, str, list[tuple[str, str, str]]]]:
    """Search arXiv and return [(arxiv_id, title, [(author, affil), ...])]."""
    q = urllib.parse.quote(query)
    url = f"http://export.arxiv.org/api/query?search_query=all:{q}&max_results={max_results}&sortBy=submittedDate&sortOrder=descending"
    logger.info(f"  Query: {query} (max={max_results})")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "hfpclawer/0.13.0"})
        with urllib.request.urlopen(req, timeout=20) as resp:
            xml_data = resp.read().decode("utf-8")
    except Exception as e:
        logger.warning(f"  FAILED: {e}")
        return []

    root = ET.fromstring(xml_data)
    results = []
    for entry in root.findall("a:entry", NS):
        title_el = entry.find("a:title", NS)
        title = title_el.text.strip().replace("\n", " ") if title_el is not None and title_el.text else "Untitled"

        id_el = entry.find("a:id", NS)
        arxiv_id = ""
        if id_el is not None and id_el.text:
            arxiv_id = id_el.text.strip().split("/")[-1].replace("arXiv:", "")

        authors = []
        for auth_el in entry.findall("a:author", NS):
            name_el = auth_el.find("a:name", NS)
            name = name_el.text.strip() if name_el is not None and name_el.text else "?"
            affil_el = auth_el.find("arxiv:affiliation", NS)
            affil = affil_el.text.strip() if affil_el is not None and affil_el.text else ""
            authors.append((name, affil))

        results.append((arxiv_id, title, authors))

    return results


def _match_institution(affil: str) -> str | None:
    """Return target institution node ID if affiliation matches."""
    affil_lower = affil.lower()
    for inst_id, keywords in TARGET_INSTS.items():
        for kw in keywords:
            if kw in affil_lower:
                return inst_id
    return None


def enrich_fusion_papers(G: nx.Graph) -> dict:
    """Search arXiv for fusion papers from target institutions and add to graph."""
    stats = {"papers": 0, "persons": 0, "affiliations": 0, "institutions_matched": set()}

    seen_papers = set()

    for query in FUSION_QUERIES:
        results = _arxiv_search(query, max_results=20)
        time.sleep(3.5)  # arXiv rate limit: 1 req/3s

        for arxiv_id, title, authors in results:
            if arxiv_id in seen_papers:
                continue
            seen_papers.add(arxiv_id)

            # Check if any author's affiliation matches a target institution
            matched_insts: dict[str, list[str]] = {}  # inst_id → [author_names]
            matched_authors: list[tuple[str, str, str]] = []  # (name, affil, inst_id)

            for author_name, affil in authors:
                if not affil:
                    continue
                inst_id = _match_institution(affil)
                if inst_id:
                    matched_authors.append((author_name, affil, inst_id))
                    matched_insts.setdefault(inst_id, []).append(author_name)

            if not matched_authors:
                continue

            logger.info(f"\n  ✅ {arxiv_id}: {title[:70]}")
            for name, affil, inst_id in matched_authors:
                inst_name = inst_id.replace("institution:", "").replace("-", " ").title()[:30]
                logger.info(f"     👤 {name:25s} @ {affil[:40]:40s} → {inst_name}")

            # Create PAPER node
            pid = paper_node_id(arxiv_id=arxiv_id)
            if pid not in G:
                G.add_node(pid, type=NodeType.PAPER, label=title[:80],
                           title=title, arxiv_id=arxiv_id, year=arxiv_id[:4] if len(arxiv_id) >= 4 else "2024",
                           source="arxiv:fusion-enrich")
                stats["papers"] += 1

            # Create PERSON nodes + AFFILIATED_WITH + AUTHOR_OF edges
            for author_name, affil, inst_id in matched_authors:
                # Parse name
                parts = author_name.split(",", 1)
                if len(parts) == 2:
                    last, first = parts[0].strip(), parts[1].strip()
                else:
                    parts = author_name.rsplit(" ", 1)
                    if len(parts) == 2 and len(parts[1]) > 1:
                        last, first = parts[1], parts[0]
                    else:
                        last, first = author_name, ""

                pers_id = person_node_id(last, first)
                if pers_id not in G:
                    G.add_node(pers_id, type=NodeType.PERSON,
                               label=f"{last}, {first[:30]}",
                               last_name=last, first_name=first)
                    stats["persons"] += 1

                # AUTHOR_OF edge
                if not G.has_edge(pers_id, pid):
                    G.add_edge(pers_id, pid, type=EdgeType.AUTHOR_OF)
                    stats["affiliations"] += 1

                # AFFILIATED_WITH edge
                if inst_id in G and not G.has_edge(pers_id, inst_id):
                    G.add_edge(pers_id, inst_id, type=EdgeType.AFFILIATED_WITH)
                    stats["affiliations"] += 1
                    stats["institutions_matched"].add(inst_id)

    stats["institutions_matched"] = len(stats["institutions_matched"])
    return stats


def main():
    # Load graph
    graph_path = Path.home() / ".hermes" / "graph_cache.pkl"
    logger.info(f"Loading graph from {graph_path}...")
    with open(graph_path, "rb") as f:
        G = pickle.load(f)
    logger.info(f"Graph: {G.number_of_nodes()} nodes, {G.number_of_edges()} edges")

    # Enrich
    logger.info("\n=== Searching arXiv for fusion papers from Chinese institutions ===")
    stats = enrich_fusion_papers(G)
    logger.info(f"\n=== Results ===")
    logger.info(f"  New papers:     {stats['papers']}")
    logger.info(f"  New persons:    {stats['persons']}")
    logger.info(f"  New edges:      {stats['affiliations']}")
    logger.info(f"  Institutions:   {stats['institutions_matched']}")

    # Save enriched graph
    backup = graph_path.with_suffix(".pkl.bak")
    graph_path.rename(backup)
    logger.info(f"\nBackup saved to {backup}")

    with open(graph_path, "wb") as f:
        pickle.dump(G, f)
    logger.info(f"Enriched graph saved to {graph_path}")

    # Validate
    from hfpapers.graph.viz.geo_map import aggregate_institution_communities
    loc_comm = aggregate_institution_communities(G, min_papers=0)
    logger.info(f"\n=== Map locations after enrichment ===")
    for nid, info in sorted(loc_comm.items(), key=lambda x: (x[1]["total_papers"] > 0, x[1]["total_papers"]), reverse=True):
        has_data = "✅" if info["total_papers"] > 0 else "⚪"
        logger.info(f"  {has_data} {info['label']:45s} | {info['total_papers']:3d} papers")


if __name__ == "__main__":
    main()
