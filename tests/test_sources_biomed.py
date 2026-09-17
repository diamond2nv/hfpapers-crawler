"""Offline parsing tests for the biomedical sources (no network).

Samples are the real response shapes captured in Task 0 (2026-09-11) — see
.hermes/plans/2026-09-11_193057-bio-source-expansion.md for the raw probe output.
"""

from hfpapers.sources import BiorxivSource, EuropePmcSource, SourcePaper

# Structurally identical to a real /search response (Task 0, 2026-09-11); all
# identifying values are placeholders per AGENTS.md rule 1 (no real authors,
# titles, DOIs or PMIDs in tracked files).
SAMPLE = {
    "version": "6.9",
    "hitCount": 309,
    "resultList": {
        "result": [
            {
                "id": "12345678",
                "source": "MED",
                "pmid": "12345678",
                "doi": "10.1000/example.1",
                "title": "Example study on diagnostic accuracy of an AI triage model.",
                "authorString": "Doe J, Smith A.",
                # The journal is nested under journalInfo.journal.title — there is no
                # flat journalTitle key in a core response (verified 2026-09-11).
                "journalInfo": {"journal": {"title": "Example Journal of Diagnostics"}},
                "pubYear": "2026",  # NOTE: a string, not an int
                "abstractText": (
                    "Example abstract: diagnostic accuracy was assessed against a reference"
                    " standard, and the discussion covers threshold selection and cost."
                ),
                "citedByCount": 0,
                "pubType": "review; journal article",
                "isOpenAccess": "N",
            }
        ]
    },
}


def test_sourcepaper_has_year_field() -> None:
    """year is a first-class field, added for biomedical sources."""
    assert SourcePaper(title="x", year=2026).year == 2026
    # a default keeps every existing source valid without changes
    assert SourcePaper().year == 0


def test_europepmc_parses_sample() -> None:
    papers = EuropePmcSource._parse(SAMPLE)
    assert len(papers) == 1
    p = papers[0]
    assert p.title.startswith("Example study on diagnostic accuracy")
    assert p.doi == "10.1000/example.1"
    assert p.year == 2026  # pubYear arrives as a STRING -> must be int()-ed
    assert p.source == "europepmc"
    assert p.abstract.startswith("Example abstract")
    assert p.venue == "Example Journal of Diagnostics"  # journalInfo.journal.title


def test_europepmc_handles_missing_fields() -> None:
    papers = EuropePmcSource._parse({"resultList": {"result": [{"title": "only a title"}]}})
    assert len(papers) == 1
    p = papers[0]
    assert p.title == "only a title"
    assert p.doi == ""
    assert p.abstract == ""
    assert p.year == 0


def test_europepmc_tolerates_empty_payload() -> None:
    assert EuropePmcSource._parse({}) == []
    assert EuropePmcSource._parse({"resultList": {}}) == []
    assert EuropePmcSource._parse({"resultList": {"result": []}}) == []


def test_europepmc_name() -> None:
    assert EuropePmcSource().name == "europepmc"


# ── bioRxiv / medRxiv (date-range API) ───────────────────────────────────────
# Structurally identical to a real /details response (Task 0, 2026-09-11);
# all identifying values are placeholders per AGENTS.md rule 1.

BIORXIV_SAMPLE = {
    "messages": [
        {
            "status": "ok",
            "category": "all",
            "interval": "2026-09-01:2026-09-03",
            "cursor": 0,
            "count": 30,
            "count_new_papers": 636,
            "total": 861,
        }
    ],
    "collection": [
        {
            "title": "Example preprint on adaptive nitrogen handling in a model organism",
            "authors": "Doe, J.; Smith, A.",
            "author_corresponding": "Jane Doe",
            "author_corresponding_institution": "Example University",
            "doi": "10.1101/2026.09.01.000001",
            "date": "2026-09-01",
            "version": "1",
            "type": "new results",
            "license": "cc_by_nc_nd",
            "category": "physiology",
            "jatsxml": "https://example.org/content/early/2026/09/01/000001.source.xml",
            "abstract": "Example abstract: this preprint studies nitrogen handling.",
            "server": "biorxiv",
        }
    ],
}


def test_biorxiv_parses_collection() -> None:
    papers = BiorxivSource._parse(BIORXIV_SAMPLE, "biorxiv")
    assert len(papers) == 1
    p = papers[0]
    assert p.title.startswith("Example preprint on adaptive nitrogen")
    assert p.doi == "10.1101/2026.09.01.000001"
    assert p.year == 2026  # date "2026-09-01" -> year 2026
    assert p.source == "biorxiv"
    assert p.abstract.startswith("Example abstract")


def test_biorxiv_name_reflects_server() -> None:
    assert BiorxivSource("biorxiv").name == "biorxiv"
    assert BiorxivSource("medrxiv").name == "medrxiv"


def test_biorxiv_url_is_date_range() -> None:
    """bioRxiv has no keyword search: the query is a date range."""
    src = BiorxivSource("medrxiv")
    assert src.url("2026-09-01", "2026-09-03") == (
        "https://api.biorxiv.org/details/medrxiv/2026-09-01/2026-09-03/0"
    )


def test_biorxiv_tolerates_empty_payload() -> None:
    assert BiorxivSource._parse({}, "biorxiv") == []
    assert BiorxivSource._parse({"collection": []}, "biorxiv") == []


# ── cross-source dedup (Task 5) ──────────────────────────────────────────────
# Regression cover for a real defect: the original deduplicate() keyed on
# arxiv_id with `if p.arxiv_id and ...`, so every biomedical record (DOI/PMID
# only, no arxiv_id) was silently DROPPED rather than merged.


def test_dedup_keeps_papers_without_arxiv_id() -> None:
    from hfpapers.sources import deduplicate

    papers = [
        SourcePaper(title="bio one", doi="10.1101/2026.09.01.000001", source="biorxiv"),
        SourcePaper(title="bio two", doi="10.1101/2026.09.01.000002", source="biorxiv"),
    ]
    assert len(deduplicate(papers)) == 2  # previously: 0 — all dropped


def test_dedup_merges_same_doi_across_sources() -> None:
    from hfpapers.sources import deduplicate

    papers = [
        SourcePaper(title="A", doi="10.1000/EXAMPLE.1", source="europepmc"),
        SourcePaper(title="A (preprint)", doi="10.1000/example.1", source="biorxiv"),
    ]
    out = deduplicate(papers)
    assert len(out) == 1
    assert out[0].source == "europepmc"  # first occurrence wins
    assert out[0].title == "A"


def test_dedup_falls_back_to_normalised_title() -> None:
    from hfpapers.sources import deduplicate

    papers = [
        SourcePaper(title="Same Title Here"),
        SourcePaper(title="same title   here!"),  # case/space/punctuation-insensitive
    ]
    assert len(deduplicate(papers)) == 1


def test_dedup_still_prefers_arxiv_id() -> None:
    """Existing behaviour must survive: same arxiv_id dedupes, order preserved."""
    from hfpapers.sources import deduplicate

    papers = [
        SourcePaper(arxiv_id="2301.00001", title="A"),
        SourcePaper(arxiv_id="2301.00001", title="A duplicate"),
        SourcePaper(arxiv_id="2301.00002", title="B"),
    ]
    out = deduplicate(papers)
    assert [p.title for p in out] == ["A", "B"]


# ── source registration (Task 3) ─────────────────────────────────────────────


def test_biomed_sources_registered_but_off_by_default() -> None:
    """New sources are registered, yet never silently enabled."""
    import hfpapers.sources as sources

    assert "europepmc" in sources.SOURCE_CLASSES
    assert "biorxiv" in sources.SOURCE_CLASSES
    assert "medrxiv" in sources.SOURCE_CLASSES
    names = [s.name for s in sources.get_enabled_sources()]
    assert "europepmc" not in names  # default config stays hf_cli-only
    assert "biorxiv" not in names


def test_source_classes_covers_legacy_sources() -> None:
    import hfpapers.sources as sources

    for legacy in ("hf_cli", "openreview", "pwc_api", "arxiv_api"):
        assert legacy in sources.SOURCE_CLASSES


def test_medrxiv_instance_uses_medrxiv_endpoint() -> None:
    import hfpapers.sources as sources

    src = sources.SOURCE_CLASSES["medrxiv"]()
    assert isinstance(src, BiorxivSource)  # narrows the factory's PaperSource type
    assert src.name == "medrxiv"
    assert "/details/medrxiv/" in src.url("2026-09-01", "2026-09-03")


def test_enabled_sources_respects_config(monkeypatch) -> None:
    """Config can opt the biomedical sources in."""
    import hfpapers.sources as sources

    monkeypatch.setattr(
        sources,
        "cfg_get",
        lambda key, default=None: (
            ["europepmc", "biorxiv"] if key == "search.enabled" else default
        ),
    )
    assert [s.name for s in sources.get_enabled_sources()] == ["europepmc", "biorxiv"]


def test_enabled_sources_reads_search_enabled(monkeypatch) -> None:
    """Regression: the config key is `search.enabled`, not `sources.enabled`.

    Reading the wrong key meant config.yaml's four enabled sources never took
    effect — get_enabled_sources() silently fell back to its ["hf_cli"] default,
    so one source ran while the config claimed four.
    """
    import hfpapers.sources as sources

    seen: list[str] = []

    def fake_cfg_get(key: str, default=None):
        seen.append(key)
        if key == "search.enabled":
            return ["hf_cli", "pwc_api", "openreview", "arxiv_api"]
        return default

    monkeypatch.setattr(sources, "cfg_get", fake_cfg_get)
    names = [s.name for s in sources.get_enabled_sources()]
    assert names == ["hf_cli", "pwc_api", "openreview", "arxiv_api"]
    assert "search.enabled" in seen
    assert "sources.enabled" not in seen
