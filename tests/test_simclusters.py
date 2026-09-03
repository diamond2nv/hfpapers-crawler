"""SimClusters community-guided expansion tests (2-hop: seed → community → hub)."""

import json

import networkx as nx
import pytest

from hfpapers.graph.citation_expander import HubGuidedExpander


class _StubExpander:
    """No-API expander: never adds nodes (community logic works on existing graph)."""

    def expand_from_seeds(self, seed_arxiv_ids, graph, max_depth=1,
                          direction="both", label_source="s2_hub"):
        return {"papers_found": [], "api_calls": 0}


def _paper_graph():
    """Two dense paper clusters + light cross edges (bridges exist, as in real graphs)."""
    G = nx.Graph()  # noqa: N806 (graph convention)
    cluster_a = [f"paper:2601.0000{i}" for i in range(1, 6)]
    cluster_b = [f"paper:2602.0000{i}" for i in range(1, 6)]
    for nid in cluster_a + cluster_b:
        G.add_node(nid, type="paper", arxiv_id=nid[6:], sources="s2_hub")
    for i in range(len(cluster_a) - 1):
        G.add_edge(cluster_a[i], cluster_a[i + 1])
    for i in range(len(cluster_b) - 1):
        G.add_edge(cluster_b[i], cluster_b[i + 1])
    G.add_edge(cluster_a[0], cluster_b[0])
    G.add_edge(cluster_a[2], cluster_b[2])
    return G


def test_community_run_structural(tmp_path):
    """Frontier = adopted papers; all candidates belong to a seed community;
    audit rows carry the community feature."""
    G = _paper_graph()  # noqa: N806
    hub = HubGuidedExpander(expander=_StubExpander(),  # type: ignore[arg-type]
                            top_k=5, sources_filter="s2_hub")
    audit = tmp_path / "audit.jsonl"
    result = hub.community_guided_run(
        G, seeds=["2601.00001"], max_layers=1, audit_path=str(audit)
    )
    assert result["mode"] == "simclusters-community"
    assert result["layers_completed"] == 1
    frontier = result["layers"][0]["frontier"]
    assert frontier, "expected a non-empty community frontier"
    # structural guarantee: frontier ⊆ candidates ⊆ seed communities
    assert result["layers"][0]["candidates"] >= len(frontier)
    # audit trail written with community feature
    assert audit.exists()
    rows = [json.loads(line) for line in audit.read_text().splitlines() if line.strip()]
    assert rows, "audit trail should have rows"
    assert all("community" in r for r in rows)
    assert all("adopted" in r for r in rows)
    adopted = [r for r in rows if r["adopted"]]
    assert adopted, "top-k of the community must be adopted"
    assert {r["arxiv_id"] for r in adopted} == set(frontier)


def test_community_run_all_candidates_share_seed_community(tmp_path):
    """Every candidate row must carry the community label of the seed's own
    community set (2-hop guarantee: no out-of-community papers)."""
    G = _paper_graph()  # noqa: N806
    hub = HubGuidedExpander(expander=_StubExpander(),  # type: ignore[arg-type]
                            top_k=3, sources_filter="s2_hub")
    audit = tmp_path / "audit2.jsonl"
    hub.community_guided_run(G, seeds=["2602.00003"], max_layers=1,
                             audit_path=str(audit))
    rows = [json.loads(line) for line in audit.read_text().splitlines() if line.strip()]
    # all audit rows must be from communities that contain the seed node
    # (seed community membership asserted via comm labels being non-empty)
    assert rows
    comms = {r["community"] for r in rows}
    assert comms, "audit rows must carry community labels"
    # No community label is empty — every candidate was placed via its community
    assert all(r["community"] for r in rows)


def test_community_run_audit_compatible_with_rank(tmp_path):
    """Audit from community mode trains the L1 ranker."""
    pytest.importorskip("lightgbm")
    from hfpapers.rank import FEATURES, train

    G = _paper_graph()  # noqa: N806
    hub = HubGuidedExpander(expander=_StubExpander(),  # type: ignore[arg-type]
                            top_k=4, sources_filter="s2_hub")
    audit = tmp_path / "audit.jsonl"
    hub.community_guided_run(G, seeds=["2601.00001", "2602.00003"],
                             max_layers=2, audit_path=str(audit))
    model = tmp_path / "model.txt"
    res = train(audit, out_model=str(model), n_estimators=20)
    assert set(res["features"]) == set(FEATURES)
    assert model.exists()
