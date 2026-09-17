"""Retry policy shared by all PaperSource implementations.

Regression cover for a real gap: sources.py never consulted `anti_crawl.*`, so
every source did `if resp.status_code != 200: return []`. A single transient 503
(observed live from Europe PMC on 2026-09-11, with bioRxiv timing out in the
same run) therefore silently dropped a whole batch of results.
"""


class _FakeResp:
    def __init__(self, status_code: int) -> None:
        self.status_code = status_code
        self.text = ""

    def json(self) -> dict:
        return {"resultList": {"result": []}, "collection": []}


def _patch(monkeypatch, statuses, *, raise_first: bool = False):
    """Fake requests.get yielding `statuses` in order; records call count."""
    import hfpapers.sources as sources

    calls = {"n": 0}

    def fake_get(url, **kwargs):
        idx = min(calls["n"], len(statuses) - 1)
        calls["n"] += 1
        if raise_first and calls["n"] == 1:
            raise sources.requests.ConnectionError("simulated network error")
        return _FakeResp(statuses[idx])

    monkeypatch.setattr(sources.requests, "get", fake_get)
    monkeypatch.setattr(sources.time, "sleep", lambda *a, **k: None)  # never really wait
    return calls


def test_get_retries_transient_503_then_succeeds(monkeypatch):
    import hfpapers.sources as sources

    calls = _patch(monkeypatch, [503, 503, 200])
    resp = sources.EuropePmcSource()._get("https://example.org/x", timeout=1)
    assert resp is not None
    assert resp.status_code == 200
    assert calls["n"] == 3


def test_get_gives_up_after_max_retries(monkeypatch):
    import hfpapers.sources as sources

    calls = _patch(monkeypatch, [503])
    assert sources.EuropePmcSource()._get("https://example.org/x", timeout=1) is None
    assert calls["n"] == 3  # anti_crawl.max_retries default


def test_get_does_not_retry_non_retryable_code(monkeypatch):
    import hfpapers.sources as sources

    calls = _patch(monkeypatch, [404])
    assert sources.EuropePmcSource()._get("https://example.org/x", timeout=1) is None
    assert calls["n"] == 1  # 404 is not in anti_crawl.retry_http_codes


def test_get_retries_on_connection_error(monkeypatch):
    import hfpapers.sources as sources

    calls = _patch(monkeypatch, [200], raise_first=True)
    resp = sources.EuropePmcSource()._get("https://example.org/x", timeout=1)
    assert resp is not None and resp.status_code == 200
    assert calls["n"] == 2


def test_get_honours_configured_max_retries(monkeypatch):
    import hfpapers.sources as sources

    monkeypatch.setattr(sources, "cfg_get", lambda key, default=None: 5 if key == "anti_crawl.max_retries" else default)
    calls = _patch(monkeypatch, [503])
    assert sources.EuropePmcSource()._get("https://example.org/x", timeout=1) is None
    assert calls["n"] == 5


def test_biorxiv_search_routes_through_retrying_get(monkeypatch):
    """Source-level search must use _get so all sources share one policy."""
    import hfpapers.sources as sources

    calls = _patch(monkeypatch, [503, 200])
    papers = sources.BiorxivSource("biorxiv").search("2026-09-01/2026-09-02")
    assert calls["n"] == 2  # retried once, then parsed
    assert papers == []


def test_europepmc_search_routes_through_retrying_get(monkeypatch):
    import hfpapers.sources as sources

    calls = _patch(monkeypatch, [503, 200])
    papers = sources.EuropePmcSource().search('TITLE:"x"')
    assert calls["n"] == 2
    assert papers == []
