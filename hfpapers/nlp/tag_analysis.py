#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tag analysis: TF-IDF scan of Zotero library for tag optimization.

Scans all items in the Zotero library, extracts candidate tags using spaCy,
and computes TF-IDF to find high-value terms that are NOT yet used as tags.

Outputs:
  - Suggested new tags (high TF-IDF, zero coverage)
  - Undertagged terms (high frequency, low coverage)
  - Tag frequency bar chart (matplotlib) or word cloud (optional wordcloud pkg)

Usage:
    from hfpapers.nlp.tag_analysis import analyze_library_tags, report_text
    client = ZoteroClient()
    analysis = analyze_library_tags(client, limit=200)
    print(report_text(analysis))
    report_chart(analysis, "tag_report.png")
"""

from __future__ import annotations

import logging
import math
import re
from collections import Counter, defaultdict
from typing import Optional

from hfpapers.nlp import get_nlp, has_spacy
from hfpapers.nlp.tags import generate_tags, DOMAIN_TAGS, _normalize_tag

logger = logging.getLogger("hfpapers.nlp.tag_analysis")

# ── Types ──────────────────────────────────────────────────────

PaperTagInfo = dict[str, any]


# ── Core analysis pipeline ─────────────────────────────────────


def scan_library_tags(
    client,
    limit: int = 200,
    batch_size: int = 50,
) -> list[PaperTagInfo]:
    """Fetch Zotero items and extract candidate tags for each.

    Args:
        client: ZoteroClient instance (connected to local API).
        limit: Max items to scan (default 200, set higher for full library).
        batch_size: Items per API call.

    Returns:
        List of dicts with keys: key, title, existing_tags, candidate_tags.
    """
    results: list[PaperTagInfo] = []
    nlp = get_nlp()

    for offset in range(0, min(limit, 1000), batch_size):
        batch = client.top(limit=batch_size, start=offset)
        if not batch:
            break

        for item in batch:
            data = item.get("data", {}) or {}
            title = data.get("title", "")
            if not title:
                continue

            # Existing tags from Zotero
            raw_tags = data.get("tags", []) or []
            existing = sorted({t.get("tag", "") for t in raw_tags if t.get("tag")})

            # Abstract (if available)
            abstract = data.get("abstractNote", "")

            # Candidate tags from spaCy
            candidate = generate_tags(title, abstract, nlp=nlp)

            results.append({
                "key": data.get("key", ""),
                "title": title[:80],
                "existing_tags": existing,
                "candidate_tags": candidate,
            })

        logger.info("Scanned %d/%d items...", offset + len(batch), limit)

    return results


def compute_tfidf(
    papers: list[PaperTagInfo],
) -> dict[str, dict]:
    """Compute TF-IDF on candidate tags across the library.

    Each paper = document. Each candidate tag = term.
    TF-IDF = (1 + log(tf)) * log(N / df)

    Returns:
        Dict mapping tag term → {tf, df, tfidf, papers_count, sample_titles}.
    """
    N = len(papers)

    # Term frequency (per document) and document frequency
    tf_counter: dict[str, int] = Counter()    # Total occurrences across papers
    df_counter: dict[str, int] = Counter()    # Number of papers containing term

    term_to_titles: dict[str, list[str]] = defaultdict(list)

    for paper in papers:
        tags = paper["candidate_tags"]
        seen = set()
        for tag in tags:
            tag_lower = tag.lower()
            tf_counter[tag_lower] += 1
            term_to_titles[tag_lower].append(paper["title"])
            if tag_lower not in seen:
                seen.add(tag_lower)
                df_counter[tag_lower] += 1

    # Compute TF-IDF
    result: dict[str, dict] = {}
    for term, tf in tf_counter.items():
        df = df_counter.get(term, 1)
        tfidf = (1 + math.log10(tf)) * math.log10(N / max(df, 1))
        result[term] = {
            "tf": tf,
            "df": df,
            "tfidf": round(tfidf, 4),
            "papers_count": df,
            "sample_titles": term_to_titles[term][:3],
        }

    return result


def find_tag_gaps(
    tfidf_scores: dict[str, dict],
    all_existing_tags: set[str],
    top_n: int = 30,
    min_tf: int = 2,
) -> list[dict]:
    """Find high-TF-IDF terms NOT yet used as tags.

    Args:
        tfidf_scores: Output of ``compute_tfidf``.
        all_existing_tags: Set of all tags currently in use across the library.
        top_n: Max suggestions to return.
        min_tf: Minimum term frequency to consider.

    Returns:
        List of dicts sorted by TF-IDF descending:
        {term, tf, df, tfidf, coverage, sample_titles}
    """
    existing_lower = {t.lower().replace("-", " ").replace("_", " ")
                      for t in all_existing_tags}

    gaps = []
    for term, info in tfidf_scores.items():
        if info["tf"] < min_tf:
            continue

        # Check if this term (or close variant) is already a tag
        term_normalized = term.lower().replace("-", " ").replace("_", " ")
        if term_normalized in existing_lower:
            continue
        # Check partial overlap (if tag contains most of the term words)
        term_words = set(term_normalized.split())
        if any(term_words.intersection(tag_words := e.split())
               and len(term_words & tag_words) / max(len(term_words), 1) >= 0.8
               for e in existing_lower):
            continue

        # Coverage: what fraction of papers with this term already have close tags
        coverage = _estimate_coverage(term_normalized, existing_lower)

        gaps.append({
            "term": term,
            "tf": info["tf"],
            "df": info["df"],
            "tfidf": info["tfidf"],
            "coverage": round(coverage, 2),
            "sample_titles": info["sample_titles"],
        })

    gaps.sort(key=lambda x: -x["tfidf"])
    return gaps[:top_n]


def _estimate_coverage(term: str, existing_tags: set[str]) -> float:
    """Estimate how well existing tags cover this term.

    Returns fraction [0, 1] of term words already present in existing tags.
    """
    words = set(term.split())
    if not words:
        return 1.0
    matched = 0
    for w in words:
        if any(w in tag or tag in w for tag in existing_tags):
            matched += 1
    return matched / len(words)


def analyze_library_tags(
    client,
    limit: int = 200,
    top_n: int = 30,
) -> dict:
    """Full tag analysis pipeline: scan → TF-IDF → gap detection → summary.

    Args:
        client: ZoteroClient instance.
        limit: Max papers to scan.
        top_n: How many gap suggestions to return.

    Returns:
        Dict with keys: n_papers, total_existing_tags, total_candidate_tags,
        top_tags, existing_tag_freq, tag_gaps.
    """
    papers = scan_library_tags(client, limit=limit)

    # Collect all existing tags and their frequency
    existing_counter: Counter = Counter()
    for p in papers:
        for tag in p["existing_tags"]:
            existing_counter[tag.lower()] += 1

    # Candidate tag count
    candidate_counter: Counter = Counter()
    for p in papers:
        for tag in p["candidate_tags"]:
            candidate_counter[tag.lower()] += 1

    # TF-IDF on candidate tags
    tfidf = compute_tfidf(papers)

    # Find gaps
    all_existing = set(existing_counter.keys())
    gaps = find_tag_gaps(tfidf, all_existing, top_n=top_n)

    return {
        "n_papers": len(papers),
        "total_existing_tags": len(all_existing),
        "total_candidate_tags": len(candidate_counter),
        # Top existing tags (most used)
        "existing_tag_freq": existing_counter.most_common(40),
        # Top candidate tags (overall)
        "top_candidate_tags": candidate_counter.most_common(40),
        # Gaps: high TF-IDF, not tagged
        "tag_gaps": gaps,
    }


# ── Reporting ──────────────────────────────────────────────────


def report_text(analysis: dict) -> str:
    """Format the tag analysis as a human-readable markdown report."""
    lines = []
    lines.append("## 📊 Zotero Tag Analysis Report")
    lines.append("")
    lines.append(f"| Metric | Value |")
    lines.append(f"|:-------|:-----:|")
    lines.append(f"| Papers scanned | {analysis['n_papers']} |")
    lines.append(f"| Existing unique tags | {analysis['total_existing_tags']} |")
    lines.append(f"| spaCy candidate tags | {analysis['total_candidate_tags']} |")
    lines.append("")

    # Top tags currently in use
    lines.append("### 🔖 Top Existing Tags (highest paper count)")
    lines.append("")
    lines.append("| Tag | Papers | % Coverage |")
    lines.append("|:----|:------:|:----------:|")
    n = analysis["n_papers"]
    for tag, count in analysis["existing_tag_freq"][:15]:
        pct = round(count / max(n, 1) * 100)
        bar = "#" * (pct // 5) + "·" * (20 - pct // 5) if pct < 100 else "#" * 20
        lines.append(f"| {tag} | {count} | {pct}% {bar} |")
    lines.append("")

    # Top candidate tags
    lines.append("### 🏷️ Top spaCy-Detected Candidates")
    lines.append("")
    lines.append("| Term | Papers | TF-IDF |")
    lines.append("|:----|:------:|:------:|")
    for tag, count in analysis["top_candidate_tags"][:15]:
        lines.append(f"| {tag} | {count} | — |")
    lines.append("")

    # Tag gaps (suggestions)
    gaps = analysis["tag_gaps"]
    if gaps:
        lines.append("### 💡 Suggested New Tags (high TF-IDF, currently untagged)")
        lines.append("")
        lines.append("| Term | Papers | TF-IDF | Coverage | Sample Title |")
        lines.append("|:----|:------:|:------:|:--------:|:------------|")
        for g in gaps[:15]:
            sample = g["sample_titles"][0][:50] if g["sample_titles"] else ""
            coverage_bar = "🟢" if g["coverage"] > 0.5 else "🟡" if g["coverage"] > 0.2 else "🔴"
            lines.append(f"| **{g['term']}** | {g['df']} | {g['tfidf']} | {coverage_bar} {g['coverage']:.0%} | {sample}")
        lines.append("")
        lines.append(f"> {len(gaps)} tag suggestions available (top {len(gaps)} by TF-IDF)")
    else:
        lines.append("### ✅ No significant tag gaps detected")
        lines.append("")

    return "\n".join(lines)


def report_chart(
    analysis: dict,
    output_path: str = "tag_report.png",
    top_n: int = 20,
) -> Optional[str]:
    """Generate a bar chart of top existing vs suggested tags.

    Requires matplotlib. Falls back to ASCII box drawing if unavailable.

    Args:
        analysis: Output of ``analyze_library_tags``.
        output_path: Where to save the chart image.
        top_n: How many top items to show.

    Returns:
        Path to the saved image, or None if matplotlib unavailable.
    """
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import numpy as np
    except ImportError:
        logger.warning("matplotlib not available — skipping chart")
        return None

    gaps = analysis["tag_gaps"][:top_n]
    if not gaps:
        return None

    # Two panels: existing tag frequency + suggested gaps
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(16, 8))
    fig.patch.set_facecolor("#1a1a2e")

    # Panel 1: existing tags
    ex_tags = analysis["existing_tag_freq"][:top_n]
    ex_names = [t[0][:25] for t in reversed(ex_tags)]
    ex_counts = [t[1] for t in reversed(ex_tags)]
    bars1 = ax1.barh(range(len(ex_names)), ex_counts, color="#4a9eff", edgecolor="white", linewidth=0.5)
    ax1.set_yticks(range(len(ex_names)))
    ax1.set_yticklabels(ex_names, fontsize=8, color="white")
    ax1.set_xlabel("Papers", color="white", fontsize=10)
    ax1.set_title("Existing Tags (top %d)" % top_n, color="white", fontsize=12, fontweight="bold")
    ax1.tick_params(colors="white")
    ax1.set_facecolor("#16213e")
    for spine in ax1.spines.values():
        spine.set_color("#333")

    # Panel 2: suggested gaps
    gap_names = [g["term"][:25] for g in reversed(gaps)]
    gap_scores = [g["tfidf"] for g in reversed(gaps)]
    gap_counts = [g["df"] for g in reversed(gaps)]
    colors = ["#ff6b6b" if g["coverage"] < 0.3 else "#ffd93d" if g["coverage"] < 0.6 else "#6bcb77"
              for g in reversed(gaps)]
    bars2 = ax2.barh(range(len(gap_names)), gap_scores, color=colors, edgecolor="white", linewidth=0.5)
    ax2.set_yticks(range(len(gap_names)))
    ax2.set_yticklabels(gap_names, fontsize=8, color="white")
    ax2.set_xlabel("TF-IDF (dot = paper count)", color="white", fontsize=10)
    ax2.set_title("Suggested Tags (top %d by TF-IDF)" % top_n, color="white", fontsize=12, fontweight="bold")
    ax2.tick_params(colors="white")
    ax2.set_facecolor("#16213e")
    for spine in ax2.spines.values():
        spine.set_color("#333")

    # Annotate with paper count
    for i, (bar, count) in enumerate(zip(bars2, gap_counts)):
        ax2.text(bar.get_width() + 0.2, bar.get_y() + bar.get_height() / 2,
                 f"({count})", va="center", fontsize=7, color="#aaa")

    plt.tight_layout()
    plt.savefig(output_path, dpi=150, bbox_inches="tight",
                facecolor="#1a1a2e", edgecolor="none")
    plt.close()
    logger.info("Tag report chart saved: %s", output_path)
    return output_path


def plot_simple_wordcloud(
    analysis: dict,
    output_path: str = "tag_wordcloud.png",
) -> Optional[str]:
    """Generate a word cloud from tag candidate frequencies.

    Requires the ``wordcloud`` package. Falls back gracefully.

    Args:
        analysis: Output of ``analyze_library_tags``.
        output_path: Where to save the word cloud image.

    Returns:
        Path to the saved image, or None if wordcloud unavailable.
    """
    try:
        from wordcloud import WordCloud
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        logger.info("wordcloud not installed — use: uv add wordcloud")
        return report_chart(analysis, output_path.replace("wordcloud", "bar"), top_n=25)

    # Build frequency dict from candidate tags
    freq = {}
    for tag, count in analysis["top_candidate_tags"]:
        freq[tag] = count

    if not freq:
        return None

    wc = WordCloud(
        width=1200,
        height=800,
        background_color="#1a1a2e",
        colormap="plasma",
        max_words=100,
        random_state=42,
    ).generate_from_frequencies(freq)

    fig, ax = plt.subplots(figsize=(14, 10))
    fig.patch.set_facecolor("#1a1a2e")
    ax.imshow(wc, interpolation="bilinear")
    ax.axis("off")
    ax.set_title("Zotero Library — Tag Candidate Word Cloud", color="white",
                 fontsize=14, fontweight="bold", pad=20)
    plt.tight_layout()
    plt.savefig(output_path, dpi=150, bbox_inches="tight",
                facecolor="#1a1a2e", edgecolor="none")
    plt.close()
    logger.info("Tag wordcloud saved: %s", output_path)
    return output_path
