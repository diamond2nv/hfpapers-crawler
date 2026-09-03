"""sync-back tests: Zotero Favor → paper_store interest signal."""

import pytest

from hfpapers.paper_store import PaperStore
from hfpapers.sync_back import sync_back


class FakeClient:
    """Minimal ZoteroClient stand-in returning canned local-API items."""

    def __init__(self, items):
        self._items = items

    def items(self, tag="", limit=50):
        assert tag == "Favor"
        return self._items


def _zot_item(key, item_type, title="", doi=None, archive=None):
    """Build a Zotero local-API-shaped item (data nested under 'data')."""
    d = {"key": key, "itemType": item_type, "title": title, "collections": []}
    if doi:
        d["DOI"] = doi
    if archive:
        d["archiveID"] = archive
    d["tags"] = []
    return {"key": key, "version": 1, "data": d}


@pytest.fixture
def store(tmp_path):
    return PaperStore(db_path=str(tmp_path / "t.db"))


def _insert(store, aid, title, doi=None):
    """Insert paper + arxiv identifier directly (PaperStore is read/state layer)."""
    with store._lock, store._conn() as conn:
        cur = conn.execute(
            "INSERT INTO papers (title, abstract, source) VALUES (?, ?, ?)",
            (title, "test abstract", "arxiv"),
        )
        sf_id = cur.lastrowid
        conn.execute(
            "INSERT INTO identifiers (sf_id, id_type, id_value) VALUES (?, 'arxiv', ?)",
            (sf_id, aid),
        )
        if doi:
            conn.execute(
                "INSERT INTO identifiers (sf_id, id_type, id_value) VALUES (?, 'doi', ?)",
                (sf_id, doi),
            )
    return sf_id


def test_all_favor_items_non_scholarly_skipped(store):
    _insert(store, "2609.00001", "A Real Paper")
    items = [
        _zot_item("AAAA1", "webpage", "Blog post"),
        _zot_item("BBBB2", "computerProgram", "microduck repo"),
        _zot_item("CCCC3", "report", "Annual report"),
    ]
    st = sync_back(FakeClient(items), store)
    assert st["total"] == 3
    assert st["skipped_non_scholarly"] == 3
    assert st["scholarly"] == 0
    assert st["in_store"] == 0
    assert st["newly_favorited"] == 0


def test_scholarly_doi_match_favorites(store):
    sf = _insert(store, "2609.00002", "Fusion Paper", doi="10.1234/fusion.2026.1")
    items = [
        _zot_item("DDDD1", "journalArticle", "Fusion Paper", doi="10.1234/fusion.2026.1"),
        _zot_item("EEEE2", "webpage", "Not a paper"),
    ]
    st = sync_back(FakeClient(items), store)
    assert st["total"] == 2
    assert st["scholarly"] == 1
    assert st["in_store"] == 1
    assert st["newly_favorited"] == 1
    row = store.get_paper_by_id(sf)
    assert row.favorited == 1
    assert row.favorited_at  # timestamp set


def test_arxiv_archive_match(store):
    sf = _insert(store, "2609.00003", "ML Paper")
    items = [_zot_item("FFFF1", "preprint", "ML Paper", archive="arXiv:2609.00003")]
    st = sync_back(FakeClient(items), store)
    assert st["newly_favorited"] == 1
    assert store.get_paper_by_id(sf).favorited == 1


def test_scholarly_not_in_store_not_favorited(store):
    _insert(store, "2609.00004", "Existing Paper")
    items = [
        _zot_item("GGGG1", "journalArticle", "Unknown Paper", doi="10.9999/other.2026.9")
    ]
    st = sync_back(FakeClient(items), store)
    assert st["scholarly"] == 1
    assert st["skipped_not_in_store"] == 1
    assert st["newly_favorited"] == 0


def test_mark_false_dry_run(store):
    sf = _insert(store, "2609.00005", "Dry Paper", doi="10.1111/dry.2026.1")
    items = [_zot_item("HHHH1", "journalArticle", "Dry Paper", doi="10.1111/dry.2026.1")]
    st = sync_back(FakeClient(items), store, mark=False)
    assert st["in_store"] == 1
    assert st["newly_favorited"] == 0  # dry-run counts match but writes nothing
    assert store.get_paper_by_id(sf).favorited == 0


def test_favorited_idempotent_keeps_first_timestamp(store):
    sf = _insert(store, "2609.00006", "Idem Paper", doi="10.2222/idem.2026.1")
    items = [_zot_item("IIII1", "journalArticle", "Idem Paper", doi="10.2222/idem.2026.1")]
    sync_back(FakeClient(items), store)
    first = store.get_paper_by_id(sf).favorited_at
    sync_back(FakeClient(items), store)
    assert store.get_paper_by_id(sf).favorited_at == first  # earliest kept


def test_favor_revoked_when_tag_disappears(store):
    """Favor tag removed in Zotero → local favorited signal reverted (explicit --revoke)."""
    sf = _insert(store, "2609.00007", "Gone Paper", doi="10.3333/gone.2026.1")
    items = [_zot_item("JJJJ1", "journalArticle", "Gone Paper", doi="10.3333/gone.2026.1")]
    sync_back(FakeClient(items), store)
    assert store.get_paper_by_id(sf).favorited == 1
    # next run: user cleaned the tag → item absent → revoke (opt-in)
    st = sync_back(FakeClient([]), store, revoke=True)
    assert st["revoked_favorites"] == 1
    assert store.get_paper_by_id(sf).favorited == 0
    assert store.get_paper_by_id(sf).favorited_at == ""


def test_revocation_never_automatic(store):
    """Without explicit revoke=True nothing is ever reverted (truncation-safe)."""
    sf = _insert(store, "2609.00008", "Keep Paper", doi="10.4444/keep.2026.1")
    items = [_zot_item("KKKK1", "journalArticle", "Keep Paper", doi="10.4444/keep.2026.1")]
    sync_back(FakeClient(items), store)
    assert store.get_paper_by_id(sf).favorited == 1
    # item vanished but no --revoke → signal untouched (pull may be truncated)
    st = sync_back(FakeClient([]), store)
    assert st["revoked_favorites"] == 0
    assert store.get_paper_by_id(sf).favorited == 1  # untouched


def test_revocation_dry_run_never_writes(store):
    sf = _insert(store, "2609.00009", "Dry Gone", doi="10.5555/drygone.2026.1")
    items = [_zot_item("LLLL1", "journalArticle", "Dry Gone", doi="10.5555/drygone.2026.1")]
    sync_back(FakeClient(items), store)
    st = sync_back(FakeClient([]), store, mark=False, revoke=True)
    assert st["revoked_favorites"] == 0  # dry-run counts nothing written
    assert store.get_paper_by_id(sf).favorited == 1
