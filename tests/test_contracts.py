"""Contract model tests (pydantic — API/JSON boundary only)."""

import pytest

from hfpapers.contracts import ZoteroItem


def _raw(**over):
    base = {"key": "K1", "itemType": "journalArticle", "title": "X",
            "DOI": "", "arxivID": "", "archiveID": "", "extra": "",
            "collections": []}
    base.update(over)
    return base


def test_scholarly_by_doi():
    item = ZoteroItem.model_validate(_raw(DOI="10.1038/s41586-024-00000-0"))
    assert item.scholarly is True
    assert item.paper_identifier == ("doi", "10.1038/s41586-024-00000-0")


def test_scholarly_by_arxiv_in_archive_id():
    # Preprint-shaped: type unreliable, archiveID carries arXiv id
    item = ZoteroItem.model_validate(_raw(archiveID="arXiv:2601.12345"))
    assert item.scholarly is True
    assert item.paper_identifier[0] == "arxiv"
    assert "2601.12345" in item.paper_identifier[1]


def test_scholarly_by_arxiv_field():
    item = ZoteroItem.model_validate(_raw(itemType="preprint", arxivID="2608.27448v2"))
    assert item.scholarly is True
    assert item.paper_identifier[0] == "arxiv"


def test_doi_prefix_stripped():
    item = ZoteroItem.model_validate(_raw(DOI="doi:10.1000/xyz123"))
    assert item.doi == "10.1000/xyz123"
    assert item.scholarly is True


def test_non_scholarly_rejected():
    # Book / web page / report without scholarly identifiers
    for itype, title in [("book", "A Book"), ("webpage", "https://x.io/post"),
                         ("report", "Q3 Report")]:
        item = ZoteroItem.model_validate(_raw(itemType=itype, title=title))
        assert item.scholarly is False
        assert item.paper_identifier is None


def test_zotero_json_surface():
    raw = {"key": "K9", "itemType": "conferencePaper",
           "title": "Neural Ops", "DOI": "10.1109/CVPR.2026.1",
           "arxivID": "", "archiveID": "",
           "collections": ["COLL1", "COLL2"]}
    item = ZoteroItem.model_validate(raw)
    assert item.item_type == "conferencePaper"
    assert item.collection_keys == ["COLL1", "COLL2"]
    assert item.scholarly is True


def test_missing_required_key_fails():
    with pytest.raises(ValueError):
        ZoteroItem.model_validate({"itemType": "journalArticle", "title": "X"})


def test_extra_notes_do_not_create_false_scholarly():
    # extra field with an arxiv-like string must NOT count (only structured ids)
    item = ZoteroItem.model_validate(_raw(extra="see arXiv:9999.99999 in notes"))
    assert item.scholarly is False
