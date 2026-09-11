# -*- coding: utf-8 -*-
"""Tests for the CN-aware arXiv acquisition transport chain.

Coverage (all offline — network paths are mocked):
- URL mapping (pdf -> /pdf/, source -> /src/)
- payload sanity checks (%PDF magic; source rejects rendered PDF fallback)
- tcp_fetch error mapping (connection reset -> failed FetchResult)
- fetch_with_fallback chain: tcp fail -> quic ok; total fail -> browser hint
- quic_fetch without aioquic -> actionable InstallError message
- AsyncPdfDownloader TCP failure -> QUIC fallback (integration, mocked)
- acquisition audit: append rows, MITM-style content-drift scan alerts
"""

import asyncio
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from hfpapers.arxiv_transport import (  # noqa: E402
    FetchResult,
    _payload_ok,
    _sha256,
    acquisition_log_path,
    arxiv_url,
    browser_hint,
    fetch_with_fallback,
    file_sha256,
    log_acquisition,
    quic_fetch,
    scan_acquisitions,
    tcp_fetch,
)
from hfpapers.arxiv_transport import _h3_path

PDF_SAMPLE = b"%PDF-1.6\n" + b"x" * 6000
GZIP_SAMPLE = b"\x1f\x8b\x08\x00" + b"y" * 300  # gzip magic (payload not real gzip)
TEX_TEXT = (
    b"\\documentclass{article}\n"
    b"\\usepackage{amsmath}\n"
    b"\\title{A transport chain test}\n"
    b"\\author{Jane Doe}\n"
    b"\\begin{document}\n"
    b"\\maketitle\n"
    b"\\section{Intro}\n"
    b"Raw tex bundles are plain text without NUL bytes; this is long enough to\n"
    b"clear the minimum payload threshold and exercise the text branch.\n"
    b"\\end{document}\n"
)


# ── URL mapping ─────────────────────────────────────────────────────────

class TestUrls:
    def test_pdf_url(self):
        assert arxiv_url("2502.05171", "pdf") == "https://arxiv.org/pdf/2502.05171"

    def test_source_url_uses_src_not_eprint(self):
        # /e-print/ 301s on modern arXiv; /src/ is the live bundle path
        assert arxiv_url("2502.05171", "source") == "https://arxiv.org/src/2502.05171"


# ── Payload sanity ──────────────────────────────────────────────────────

class TestPayloadOk:
    def test_pdf_magic(self):
        assert _payload_ok(PDF_SAMPLE, "pdf")
        assert not _payload_ok(b"<html>not a pdf</html>", "pdf")
        assert not _payload_ok(PDF_SAMPLE[:100], "pdf")  # too small

    def test_source_accepts_gzip_and_text(self):
        assert _payload_ok(GZIP_SAMPLE, "source")
        assert _payload_ok(TEX_TEXT, "source")

    def test_source_rejects_rendered_pdf_fallback(self):
        # arXiv /src/ returns the PDF itself when no tex bundle was uploaded
        assert not _payload_ok(PDF_SAMPLE, "source")

    def test_source_rejects_binary_soup(self):
        assert not _payload_ok(b"\x00\x01\x02\x03" * 100, "source")


# ── tcp_fetch ───────────────────────────────────────────────────────────

class TestTcpFetch:
    def test_success(self, monkeypatch):
        class FakeResp:
            status_code = 200
            content = PDF_SAMPLE
            url = "https://arxiv.org/pdf/2502.05171"

        class FakeRequests:
            def get(self, *a, **k):
                return FakeResp()

        monkeypatch.setitem(sys.modules, "requests", FakeRequests())
        r = tcp_fetch("https://arxiv.org/pdf/2502.05171", "pdf", timeout=5)
        assert r.ok
        assert r.transport == "tcp"
        assert r.tls_verified
        assert r.sha256 == _sha256(PDF_SAMPLE)

    def test_connection_reset_maps_to_failure(self, monkeypatch):
        class FakeRequests:
            def get(self, *a, **k):
                raise ConnectionError("Connection reset by peer")  # CN-network norm

        monkeypatch.setitem(sys.modules, "requests", FakeRequests())
        r = tcp_fetch("https://arxiv.org/pdf/2502.05171", "pdf", timeout=5)
        assert not r.ok
        assert "reset" in r.error.lower()

    def test_http_error_status(self, monkeypatch):
        class FakeResp:
            status_code = 503
            content = b""
            url = "https://arxiv.org/pdf/2502.05171"

        class FakeRequests:
            def get(self, *a, **k):
                return FakeResp()

        monkeypatch.setitem(sys.modules, "requests", FakeRequests())
        r = tcp_fetch("https://arxiv.org/pdf/2502.05171", "pdf", timeout=5)
        assert not r.ok
        assert "503" in r.error


# ── quic_fetch (ImportError path — offline) ─────────────────────────────

class TestQuicImportGuard:
    def test_missing_aioquic_returns_actionable_error(self, monkeypatch):
        import builtins

        real_import = builtins.__import__

        def fake_import(name, *a, **k):
            if name == "aioquic" or name.startswith("aioquic."):
                raise ImportError("No module named 'aioquic'")
            return real_import(name, *a, **k)

        monkeypatch.setattr(builtins, "__import__", fake_import)
        r = quic_fetch("https://arxiv.org/pdf/2502.05171", "pdf", timeout=1)
        assert not r.ok
        assert "hfpclawer[quic]" in r.error  # actionable install hint


# ── fetch_with_fallback chain ───────────────────────────────────────────

class TestFallbackChain:
    def test_tcp_fail_quic_success(self, monkeypatch):
        import hfpapers.arxiv_transport as at

        monkeypatch.setattr(
            at, "tcp_fetch",
            lambda url, kind, timeout=60.0: FetchResult(
                ok=False, kind=kind, url=url, transport="tcp", error="reset",
            ),
        )
        monkeypatch.setattr(
            at, "quic_fetch",
            lambda url, kind, timeout=60.0: FetchResult(
                ok=True, kind=kind, url=url, transport="quic",
                data=PDF_SAMPLE, tls_verified=True, sha256=_sha256(PDF_SAMPLE),
            ),
        )
        r = fetch_with_fallback("2502.05171", "pdf")
        assert r.ok
        assert r.transport == "quic"

    def test_total_failure_yields_browser_hint(self, monkeypatch):
        import hfpapers.arxiv_transport as at

        monkeypatch.setattr(
            at, "tcp_fetch",
            lambda url, kind, timeout=60.0: FetchResult(
                ok=False, kind=kind, url=url, transport="tcp", error="reset",
            ),
        )
        monkeypatch.setattr(
            at, "quic_fetch",
            lambda url, kind, timeout=60.0: FetchResult(
                ok=False, kind=kind, url=url, transport="quic",
                error="no aioquic",
            ),
        )
        r = fetch_with_fallback("2502.05171", "pdf")
        assert not r.ok
        assert r.transport == "hint"
        assert "browser_navigate" in r.hint  # echo guidance for agent fallback

    def test_hint_mentions_alphaxiv_for_pdf(self):
        h = browser_hint("2502.05171", "pdf")
        assert "browser_navigate" in h and "alphaxiv.org" in h


# ── Acquisition audit ───────────────────────────────────────────────────

class TestAcquisitionAudit:
    def test_log_and_scan_clean(self, tmp_path):
        ok_row = FetchResult(
            ok=True, kind="pdf", url="https://arxiv.org/pdf/2502.05171",
            transport="quic", data=PDF_SAMPLE, tls_verified=True,
        ).audit_row("2502.05171")
        log_acquisition(ok_row, tmp_path)
        assert acquisition_log_path(tmp_path).exists()
        assert scan_acquisitions(tmp_path) == []

    def test_content_drift_alerts(self, tmp_path):
        # Same paper, same kind, DIFFERENT sha256 across transports —
        # the MITM signature: payload swapped on one channel.
        r1 = FetchResult(
            ok=True, kind="pdf", url="https://arxiv.org/pdf/2502.05171",
            transport="tcp", data=PDF_SAMPLE, tls_verified=True,
        )
        r2 = FetchResult(
            ok=True, kind="pdf", url="https://arxiv.org/pdf/2502.05171",
            transport="quic", data=b"%PDF-1.6\n" + b"z" * 6000, tls_verified=True,
        )
        log_acquisition(r1.audit_row("2502.05171"), tmp_path)
        log_acquisition(r2.audit_row("2502.05171"), tmp_path)
        alerts = scan_acquisitions(tmp_path)
        assert len(alerts) == 1
        assert alerts[0]["severity"] == "content-drift"
        assert alerts[0]["arxiv_id"] == "2502.05171"
        assert "tcp" in alerts[0]["transports"] and "quic" in alerts[0]["transports"]

    def test_rows_are_jsonl_append(self, tmp_path):
        for i in range(3):
            r = FetchResult(
                ok=True, kind="pdf", url=f"https://arxiv.org/pdf/2502.0517{i}",
                transport="quic", data=PDF_SAMPLE, tls_verified=True,
            ).audit_row(f"2502.0517{i}")
            log_acquisition(r, tmp_path)
        lines = [json.loads(ln) for ln in acquisition_log_path(tmp_path).read_text().splitlines()]
        assert len(lines) == 3
        assert all(x["event"] == "acquisition" for x in lines)


# ── Resumable fetch + file integrity ─────────────────────────────────────

class TestResumable:
    def test_full_body_hash_mismatch_rejects(self, tmp_path, monkeypatch):
        """Corrupted full-body transfer → file dropped, no false success."""
        import hfpapers.arxiv_transport as at

        dest = tmp_path / "x.pdf"
        calls = {"n": 0}

        def fake_quic(url, kind, timeout=60.0, range_from=0, sink=None, flush_every=0):
            calls["n"] += 1
            assert range_from == 0
            # Simulated corruption: data passes magic but sha mismatchs
            return FetchResult(
                ok=True, kind=kind, url=url, transport="quic",
                data=b"%PDF-corp", tls_verified=True,
                sha256="0" * 64,  # deliberately wrong
            )

        monkeypatch.setattr(at, "quic_fetch", fake_quic)
        r = at.fetch_resumable("2502.05171", dest=dest, max_rounds=2)
        assert not r.ok
        assert "sha256 mismatch" in r.error
        assert not dest.exists()  # corrupted file dropped

    def test_partial_then_resume_completes(self, tmp_path, monkeypatch):
        """Round 1 times out mid-body (partial kept) → round 2 resumes via
        Range and the assembled file matches on-disk sha256."""
        import hfpapers.arxiv_transport as at

        dest = tmp_path / "x.pdf"
        full = PDF_SAMPLE
        mid = 3000  # interrupt after 3KB of a 6KB+ body
        calls = {"n": 0}

        def fake_quic(url, kind, timeout=60.0, range_from=0, sink=None, flush_every=0):
            calls["n"] += 1
            if calls["n"] == 1:
                assert range_from == 0
                # incomplete round: partial bytes + not-finished error
                return FetchResult(
                    ok=False, kind=kind, url=url, transport="quic",
                    data=full[:mid], tls_verified=True,
                    error="HTTP 200 (incomplete — timed out mid-transfer)",
                )
            # resume round: Range from committed offset, rest arrives
            assert range_from == mid
            return FetchResult(
                ok=True, kind=kind, url=url, transport="quic",
                data=full[mid:], tls_verified=True,
                error="",
            )

        monkeypatch.setattr(at, "quic_fetch", fake_quic)
        r = at.fetch_resumable("2502.05171", dest=dest, timeout=1.0, max_rounds=3)
        assert r.ok
        assert dest.exists()
        assert dest.read_bytes() == full  # assembled exactly
        assert r.sha256 == _sha256(full)  # integrity hash == expected
        assert not dest.with_name("x.pdf.part").exists()  # .part renamed away

    def test_sink_full_body_validates_file_not_tail(self, tmp_path, monkeypatch):
        """Bugfix (2026-09-05): sink path with range_from=0 streamed the payload
        head to disk, leaving only mid-file residual bytes in memory. The old
        code ran _payload_ok on that tail → false failure → fetch_resumable
        fell into a Range-at-EOF resume loop and the .part never completed.

        Drives async_quic_fetch end-to-end with a fake aioquic connection that
        simulates a > flush_every body: head already flushed to the sink file,
        residual tail in memory. Asserts ok=True and the decision used the
        file head (gzip magic on disk), not the mid-file tail.
        """
        import hfpapers.arxiv_transport as at

        sink = tmp_path / "x.tar.gz.part"
        big = b"\x1f\x8b\x08\x00" + bytes(range(256)) * 4096  # 1MB, gzip magic
        assert len(big) > 512 * 1024
        head_bytes, tail = big[:512 * 1024], big[512 * 1024:]

        class FakeProto:
            """Stands in for aioquic _Client — events already pumped."""

            def __init__(self):
                self.body = bytearray(tail)  # residual tail in memory
                self.status = 200
                self.finished = asyncio.Event()
                self.closed = asyncio.Event()
                sink.write_bytes(head_bytes)  # head flushed to .part on disk

            def start_request(self):
                self.finished.set()  # stream_ended arrived

        class FakeConn:
            def __init__(self):
                self.proto = FakeProto()

            async def __aenter__(self):
                return self.proto

            async def __aexit__(self, *a):
                return False

        import aioquic.asyncio.client as aqc

        monkeypatch.setattr(aqc, "connect", lambda *a, **k: FakeConn())
        r = asyncio.run(at.async_quic_fetch(
            "https://arxiv.org/src/2502.05171", "source",
            timeout=5.0, range_from=0, sink=sink, flush_every=512 * 1024,
        ))
        assert r.ok, r.error
        # Old behaviour rejected the mid-file tail:
        assert not at._payload_ok(tail, "source")
        assert sink.read_bytes() == head_bytes  # file untouched by decision

    def test_sink_pdf_head_check(self, tmp_path, monkeypatch):
        """PDF sink path: %PDF head flushed to disk → file-head check passes."""
        import hfpapers.arxiv_transport as at

        sink = tmp_path / "x.pdf.part"
        big = b"%PDF-1.6\n" + bytes(range(256)) * 4096  # 1MB
        head_bytes, tail = big[:512 * 1024], big[512 * 1024:]

        class FakeProto:
            def __init__(self):
                self.body = bytearray(tail)
                self.status = 200
                self.finished = asyncio.Event()
                self.closed = asyncio.Event()
                sink.write_bytes(head_bytes)

            def start_request(self):
                self.finished.set()

        class FakeConn:
            def __init__(self):
                self.proto = FakeProto()

            async def __aenter__(self):
                return self.proto

            async def __aexit__(self, *a):
                return False

        import aioquic.asyncio.client as aqc

        monkeypatch.setattr(aqc, "connect", lambda *a, **k: FakeConn())
        r = asyncio.run(at.async_quic_fetch(
            "https://arxiv.org/pdf/2502.05171", "pdf",
            timeout=5.0, range_from=0, sink=sink, flush_every=512 * 1024,
        ))
        assert r.ok, r.error
        assert not at._payload_ok(tail, "pdf")  # old behaviour: false reject
        assert sink.read_bytes() == head_bytes

    def test_hard_failure_surfaces(self, tmp_path, monkeypatch):
        """Non-incomplete failures (e.g. connection refused) surface directly."""
        import hfpapers.arxiv_transport as at

        dest = tmp_path / "x.pdf"

        def fake_quic(url, kind, timeout=60.0, range_from=0, sink=None, flush_every=0):
            return FetchResult(ok=False, kind=kind, url=url, transport="quic",
                               error="no response from server")

        monkeypatch.setattr(at, "quic_fetch", fake_quic)
        r = at.fetch_resumable("2502.05171", dest=dest, max_rounds=3)
        assert not r.ok
        assert "no response" in r.error

    def test_file_sha256(self, tmp_path):
        p = tmp_path / "f.bin"
        p.write_bytes(PDF_SAMPLE)
        assert file_sha256(p) == _sha256(PDF_SAMPLE)

    def test_range_416_promotes_complete_part(self, tmp_path, monkeypatch):
        """Server closed the connection after delivering the whole body; the
        resume round gets 416 (offset >= length) — the .part is complete and
        is promoted to the final file instead of looping forever."""
        import hfpapers.arxiv_transport as at

        dest = tmp_path / "x.pdf"
        part = dest.with_name("x.pdf.part")
        part.write_bytes(PDF_SAMPLE)  # full body already flushed to .part
        calls = {"n": 0}

        def fake_quic(url, kind, timeout=60.0, range_from=0, sink=None, flush_every=0):
            calls["n"] += 1
            assert range_from == len(PDF_SAMPLE)
            return FetchResult(ok=False, kind=kind, url=url, transport="quic",
                               error="HTTP 416")  # Range Not Satisfiable

        monkeypatch.setattr(at, "quic_fetch", fake_quic)
        r = at.fetch_resumable("2502.05171", dest=dest, max_rounds=3)
        assert r.ok
        assert calls["n"] == 1  # no resume loop
        assert dest.exists()
        assert dest.read_bytes() == PDF_SAMPLE
        assert not part.exists()

    def test_stale_part_reclaimed(self, tmp_path, monkeypatch):
        """A .part older than stale_part_after is discarded (restart from 0),
        not resumed — dead-session orphans don't accumulate."""
        import hfpapers.arxiv_transport as at

        dest = tmp_path / "x.pdf"
        part = dest.with_name("x.pdf.part")
        part.write_bytes(b"OLD-PARTIAL-DATA-0123456789")
        # Simulate a stale .part (mtime far in the past)
        old = time.time() - 100 * 3600
        os.utime(part, (old, old))
        offsets = []

        def fake_quic(url, kind, timeout=60.0, range_from=0, sink=None, flush_every=0):
            offsets.append(range_from)
            return FetchResult(ok=True, kind=kind, url=url, transport="quic",
                               data=PDF_SAMPLE, tls_verified=True,
                               sha256=_sha256(PDF_SAMPLE))

        monkeypatch.setattr(at, "quic_fetch", fake_quic)
        r = at.fetch_resumable("2502.05171", dest=dest, max_rounds=2,
                               stale_part_after=3600)
        assert r.ok
        assert offsets == [0]  # stale part dropped → started from zero
        assert not part.exists()  # no .part residue after success

    def test_max_bytes_aborts(self, tmp_path, monkeypatch):
        """max_bytes caps the .part file — runaway payloads abort cleanly."""
        import hfpapers.arxiv_transport as at

        dest = tmp_path / "x.pdf"

        def fake_quic(url, kind, timeout=60.0, range_from=0, sink=None, flush_every=0):
            return FetchResult(
                ok=False, kind=kind, url=url, transport="quic",
                data=PDF_SAMPLE, tls_verified=True,  # partial arrives...
                error="HTTP 200 (incomplete — timed out mid-transfer)",
            )

        monkeypatch.setattr(at, "quic_fetch", fake_quic)
        r = at.fetch_resumable("2502.05171", dest=dest, max_rounds=5,
                               max_bytes=len(PDF_SAMPLE) // 2)
        assert not r.ok
        assert "max_bytes" in r.error

    def test_exception_wrapped_not_raised(self, tmp_path, monkeypatch):
        """Any internal exception becomes a failed FetchResult (never raises)
        and reports the surviving .part location."""
        import hfpapers.arxiv_transport as at

        dest = tmp_path / "x.pdf"

        def fake_quic(url, kind, timeout=60.0, range_from=0, sink=None, flush_every=0):
            raise RuntimeError("disk exploded")

        monkeypatch.setattr(at, "quic_fetch", fake_quic)
        r = at.fetch_resumable("2502.05171", dest=dest, max_rounds=2)
        assert not r.ok
        assert "disk exploded" in r.error  # wrapped, not raised


# ── AsyncPdfDownloader QUIC fallback (integration, mocked) ──────────────

class TestDownloaderQuicFallback:
    def _make_downloader(self, tmp_path):
        from hfpapers.pdf_downloader_async import AsyncPdfDownloader

        return AsyncPdfDownloader(
            max_concurrent=2,
            pdf_dir=str(tmp_path / "pdfs"),
            md_dir=str(tmp_path / "mds"),
        )

    def test_tcp_reset_falls_back_to_quic(self, tmp_path, monkeypatch):
        """aiohttp fails (CN reset) -> QUIC path saves the paper + audits it."""
        d = self._make_downloader(tmp_path)
        async def _no_md(*a, **k):
            return None

        monkeypatch.setattr(d, "_convert_to_md", _no_md)

        # TCP (aiohttp session.get) always explodes
        class BoomSession:
            def get(self, url, *a, **k):
                raise ConnectionError("Connection reset by peer")

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def close(self):
                pass

        from hfpapers import arxiv_transport as atmod
        from hfpapers.arxiv_transport import FetchResult

        async def fake_quic(url, kind, timeout=60.0):
            return FetchResult(ok=True, kind=kind, url=url, transport="quic",
                               data=PDF_SAMPLE, tls_verified=True, sha256=_sha256(PDF_SAMPLE))

        monkeypatch.setattr(atmod, "async_quic_fetch", fake_quic)
        # Route acquisition audit writes into the test dir
        audit_file = tmp_path / "download_audit.jsonl"

        def fake_log(row, data_dir=None):
            with open(audit_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(row) + "\n")
            return audit_file

        monkeypatch.setattr(atmod, "log_acquisition", fake_log)

        async def run():
            return await d._download_one(BoomSession(), {"arxiv_id": "2502.05171",
                                                         "title": "T"})

        result = asyncio.run(run())
        assert result["success"]
        pdf = tmp_path / "pdfs" / "2502.05171.pdf"
        assert pdf.exists()
        assert d._quic_used == 1
        # audit row written by the downloader path
        rows = [json.loads(ln) for ln in audit_file.read_text().splitlines()]
        assert any(x["transport"] == "quic" and x["arxiv_id"] == "2502.05171"
                   for x in rows)

    def test_quic_also_fails_marks_failed(self, tmp_path, monkeypatch):
        d = self._make_downloader(tmp_path)

        class BoomSession:
            def get(self, url, *a, **k):
                raise ConnectionError("reset")

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

        from hfpapers import arxiv_transport as atmod
        from hfpapers.arxiv_transport import FetchResult

        async def fake_quic(url, kind, timeout=60.0):
            return FetchResult(ok=False, kind=kind, url=url, transport="quic",
                               error="no aioquic / timeout")

        monkeypatch.setattr(atmod, "async_quic_fetch", fake_quic)

        async def run():
            return await d._download_one(BoomSession(), {"arxiv_id": "2502.05171",
                                                         "title": "T"})

        result = asyncio.run(run())
        assert not result["success"]
        assert "quic" in result["error"]


# ── _h3_path: the HTTP/3 :path pseudo-header must carry the query ─────────
class TestH3Path:
    """Regression: urlsplit() puts the query in parts.query, so sending only
    parts.path silently drops it. Parameterised endpoints then fail AT THE
    SERVER with a generic error (OAI -> badVerb, arXiv API -> HTTP 400),
    which reads like "QUIC does not support metadata" instead of a path bug.
    """

    def _p(self, url):
        from urllib.parse import urlsplit

        return _h3_path(urlsplit(url))

    def test_no_query_is_byte_identical_to_path(self):
        # Backwards-compat invariant: every pre-existing caller (pdf/src/abs/list)
        # has no query string, so behaviour must be unchanged.
        from urllib.parse import urlsplit

        for url in (
            "https://arxiv.org/pdf/2502.05171",
            "https://arxiv.org/src/2502.05171",
            "https://arxiv.org/abs/2608.16195",
            "https://arxiv.org/list/cs.AI/recent",
        ):
            assert self._p(url) == urlsplit(url).path.encode()

    def test_query_is_preserved(self):
        assert self._p("https://oaipmh.arxiv.org/oai?verb=Identify") == b"/oai?verb=Identify"

    def test_multi_param_query_is_preserved(self):
        got = self._p(
            "https://oaipmh.arxiv.org/oai?verb=ListRecords"
            "&metadataPrefix=arXiv&from=2026-09-01&until=2026-09-02&set=cs"
        )
        assert got.startswith(b"/oai?verb=ListRecords&")
        assert b"metadataPrefix=arXiv" in got
        assert b"set=cs" in got

    def test_percent_encoded_query_passes_through(self):
        # Caller is responsible for percent-encoding; helper must not re-encode.
        got = self._p("https://export.arxiv.org/api/query?search_query=all%3Adogfight&max_results=3")
        assert got == b"/api/query?search_query=all%3Adogfight&max_results=3"

    def test_empty_path_becomes_root(self):
        assert self._p("https://arxiv.org?verb=X") == b"/?verb=X"

    def test_trailing_question_mark_without_query(self):
        # "...?" parses as empty query -> must not emit a bare "?"
        assert self._p("https://arxiv.org/oai?") == b"/oai"

    def test_call_sites_do_not_drop_the_query(self):
        """Guard the two real call sites (single + batch).

        The helper is unit-tested above, but a caller could silently revert to
        ``parts.path.encode()`` and every test above would still pass.
        """
        import inspect

        from hfpapers import arxiv_transport as atmod

        src = inspect.getsource(atmod)
        assert "parts.path.encode()" not in src, (
            "a :path call site reverted to dropping the query string"
        )
        # 1 definition + 2 call sites (single-request + batch)
        assert src.count("_h3_path(parts)") == 3, "expected def + 2 :path call sites"
