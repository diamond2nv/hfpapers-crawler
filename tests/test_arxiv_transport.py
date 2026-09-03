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
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from hfpapers.arxiv_transport import (  # noqa: E402
    FetchResult,
    _payload_ok,
    _sha256,
    acquisition_log_path,
    arxiv_url,
    browser_hint,
    fetch_with_fallback,
    log_acquisition,
    quic_fetch,
    scan_acquisitions,
    tcp_fetch,
)

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
        lines = [json.loads(l) for l in acquisition_log_path(tmp_path).read_text().splitlines()]
        assert len(lines) == 3
        assert all(x["event"] == "acquisition" for x in lines)


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
        from hfpapers.arxiv_transport import FetchResult as FR

        async def fake_quic(url, kind, timeout=60.0):
            return FR(ok=True, kind=kind, url=url, transport="quic",
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
        rows = [json.loads(l) for l in audit_file.read_text().splitlines()]
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
        from hfpapers.arxiv_transport import FetchResult as FR

        async def fake_quic(url, kind, timeout=60.0):
            return FR(ok=False, kind=kind, url=url, transport="quic",
                      error="no aioquic / timeout")

        monkeypatch.setattr(atmod, "async_quic_fetch", fake_quic)

        async def run():
            return await d._download_one(BoomSession(), {"arxiv_id": "2502.05171",
                                                         "title": "T"})

        result = asyncio.run(run())
        assert not result["success"]
        assert "quic" in result["error"]
