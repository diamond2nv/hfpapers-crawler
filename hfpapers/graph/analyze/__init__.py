#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""hfpapers.graph.analyze — Knowledge Graph Analyzer.

Orchestrates subgraph selection, impact analysis, community detection,
actor analysis, and report generation into a unified pipeline.

Usage::

    from hfpapers.graph.analyze import Analyzer

    analyzer = Analyzer(G)
    report = analyzer.run(source="coc")
    print(report)  # Markdown string
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Optional

import networkx as nx

from hfpapers.graph.analyze import (
    actors,
    communities,
    impact,
    subgraph,
)
from hfpapers.graph.analyze import (
    report as report_fmt,
)

logger = logging.getLogger("hfpapers.graph.analyze")


class Analyzer:
    """Knowledge graph analysis orchestrator.

    Args:
        G: Full knowledge graph (networkx.Graph).
    """

    def __init__(self, G: nx.Graph):
        self.G = G

    def run(
        self,
        source: str = "coc",
        impact_algorithm: str = "all",
        community_algorithm: str = "leiden",
        resolution: float = 1.0,
        top_n: int = 20,
        output_format: str = "markdown",
        output_path: str = "",
        edge_types: Optional[set] = None,
    ) -> str:
        """Run the full analysis pipeline.

        Args:
            source: Source tag (e.g. 'coc', 'zotero', 'all').
            impact_algorithm: 'degree', 'pagerank', 'hits', 'betweenness',
                or 'all' for everything.
            community_algorithm: 'louvain', 'leiden', 'label_propagation'.
            resolution: Community detection resolution.
            top_n: Results per section.
            output_format: 'markdown' or 'json'.
            output_path: If set, save report to this file.
            edge_types: Edge types to include in subgraph.

        Returns:
            Report string (markdown or json).
        """
        from hfpapers.graph.schema import EdgeType, NodeType

        logger.info("Analyzer.run(source=%s, impact=%s, community=%s)",
                     source, impact_algorithm, community_algorithm)

        # 1. Extract citation subgraph
        citation_H = subgraph.citation_subgraph(self.G, source=source)

        if citation_H.number_of_nodes() < 3:
            return f"⚠️  Too few papers ({citation_H.number_of_nodes()}) in source '{source}' for analysis."

        # 2. Extract author-paper mappings
        auth_papers, paper_auths = subgraph.author_paper_bipartite(
            self.G, source=source
        )

        # Normalize paper IDs: strip "paper:" prefix since citation_H uses bare arXiv IDs
        def _norm_pid(pid: str) -> str:
            return pid.replace("paper:", "", 1) if pid.startswith("paper:") else pid

        auth_papers_norm: dict = {
            k: {_norm_pid(p) for p in v} for k, v in auth_papers.items()
        }
        paper_auths_norm: dict = {
            _norm_pid(k): v for k, v in paper_auths.items()
        }

        # 3. Impact analysis — use normalized paper IDs
        impact_results = impact.full_impact_report(
            citation_H, paper_auths_norm, auth_papers_norm, top_n=top_n
        )

        # 4. Community detection
        Hu = citation_H.to_undirected()
        community_results = communities.full_report(
            Hu, resolution=resolution, top_n=5, citation_H=citation_H
        )

        # 5. Actor analysis — uses LCC community sets

        # Re-run communities to get raw sets for bridge detection (on LCC only)
        import networkx as nx
        Hu_lcc = Hu.subgraph(max(nx.connected_components(Hu), key=len)) if Hu.number_of_nodes() else Hu
        try:
            preferred_cls = communities.leiden(Hu_lcc, resolution=resolution)
        except Exception:
            preferred_cls = communities.louvain(Hu_lcc, resolution=resolution)

        actor_results = actors.full_report(
            auth_papers_norm, paper_auths_norm, preferred_cls, self.G, top_n=top_n
        )

        # 6. Format output
        if output_format == "json":
            report = report_fmt.json_report(impact_results, community_results, actor_results)
        elif output_format == "qmd":
            # Generate vector figures
            from hfpapers.graph.analyze import viz as viz_module
            fig_dir = str(Path(output_path or f"~/data/kg/{source}-report.qmd").expanduser().parent / "figures")
            figures = viz_module.render_all(
                citation_H, impact_results, community_results,
                output_dir=fig_dir,
            )
            from hfpapers.graph.analyze import report_qmd as qmd_module
            title = f"Knowledge Graph Analysis: {source}"
            if source == "all":
                title = "Knowledge Graph Analysis: Full Graph"
            qmd_path = output_path or f"~/data/kg/{source}-report.qmd"
            report = qmd_module.generate_qmd(
                source=source, figures=figures,
                title=title, output_path=qmd_path,
            )
        else:
            title = f"📊 Knowledge Graph Analysis: `{source}`"
            if source == "all":
                title = "📊 Knowledge Graph Analysis: Full Graph"
            report = report_fmt.markdown_report(
                impact_results, community_results, actor_results,
                title=title, source=source,
            )

        # 7. Save if requested
        if output_path:
            path = Path(output_path).expanduser()
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(report, encoding="utf-8")
            logger.info("Report saved to %s", path)

        return report


def run_analysis(
    G: nx.Graph,
    source: str = "coc",
    impact_algorithm: str = "all",
    community_algorithm: str = "leiden",
    resolution: float = 1.0,
    top_n: int = 20,
    output_format: str = "markdown",
    output_path: str = "",
) -> str:
    """Convenience function: create Analyzer and run.

    Args:
        G: Full knowledge graph.
        **kwargs: Passed to Analyzer.run().

    Returns:
        Report string.
    """
    analyzer = Analyzer(G)
    return analyzer.run(
        source=source,
        impact_algorithm=impact_algorithm,
        community_algorithm=community_algorithm,
        resolution=resolution,
        top_n=top_n,
        output_format=output_format,
        output_path=output_path,
    )
