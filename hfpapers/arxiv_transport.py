# -*- coding: utf-8 -*-
"""arxiv_transport.py — Layered arXiv acquisition transport (CN-friendly).

China-network reality (2026-09-03, HUAWEI measured): arxiv.org TCP/443 is reset
at the TLS-SNI fingerprint layer (curl: 5/5 RST ~0.13s), while UDP/443 QUIC
(HTTP/3) is NOT reset — aioquic handshake succeeds and the server responds.
Browser engines (Chromium/Camoufox) reach arXiv directly via QUIC.

This module provides a transport chain for acquiring paper payloads:

    tcp (requests)  ->  quic (aioquic, optional extra)  ->  browser-hint (echo)

Every attempt is appended to the acquisition audit JSONL
(data/download_audit.jsonl, append-only) with transport + content-hash
evidence. Cross-transport / cross-batch sha256 comparison of the same paper
detects content tampering (MITM class: a swapped payload changes the hash).

aioquic does not expose the verified peer certificate object on the client
side, so TLS integrity rests on CERT_REQUIRED chain verification (handshake
fails on any mismatch) and payload-hash comparison — recorded honestly as
``tls_verified`` rather than claiming a fingerprint we cannot extract.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger("hfpapers.arxiv_transport")

USER_AGENT = "hfpclawer-acquisition/0.16.11 (+https://pypi.org/project/hfpclawer)"


@dataclass
class FetchResult:
    """Outcome of one transport attempt (or the full chain)."""

    ok: bool
    kind: str  # "pdf" | "source" (source = tex e-print, usually tar.gz)
    url: str
    transport: str  # "tcp" | "quic" | "hint"
    data: bytes = b""
    ms: float = 0.0
    tls_verified: bool = False
    error: str = ""
    sha256: str = ""
    hint: str = ""  # human/agent guidance when every transport failed

    def audit_row(self, arxiv_id: str) -> dict:
        payload_hash = self.sha256 or (_sha256(self.data) if self.data else "")
        return {
            "event": "acquisition",
            "arxiv_id": arxiv_id,
            "kind": self.kind,
            "transport": self.transport,
            "url": self.url,
            "ok": self.ok,
            "bytes": len(self.data),
            "ms": round(self.ms, 1),
            "tls_verified": self.tls_verified,
            "sha256": payload_hash,
            "error": self.error[:200],
            "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }


# Payload sanity markers: PDF starts with %PDF; arXiv e-print (tex source) is
# delivered as gzip (tar.gz). gzip magic = 1f 8b; some e-prints are plain
# .tex/.bbl bundles delivered as raw text — source check is relaxed.
_MAGIC = {"pdf": b"%PDF", "source": b"\x1f\x8b"}
_MIN_BYTES = {"pdf": 5000, "source": 200}


def _payload_ok(data: bytes, kind: str) -> bool:
    if len(data) < _MIN_BYTES.get(kind, 200):
        return False
    if kind == "source":
        # arXiv /src/ returns the PDF itself for submissions that never
        # uploaded a tex bundle — reject rendered content.
        if data.startswith(b"%PDF"):
            return False
        # Legit source bundles: gzip tar (1f 8b) OR raw tex text (no NULs).
        if data.startswith(b"\x1f\x8b"):
            return True
        return b"\x00" not in data
    return data.startswith(_MAGIC[kind])


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def arxiv_url(arxiv_id: str, kind: str = "pdf") -> str:
    base = "https://arxiv.org"
    if kind == "pdf":
        return f"{base}/pdf/{arxiv_id}"
    return f"{base}/src/{arxiv_id}"  # tex source bundle (/e-print/ 301s)


def tcp_fetch(url: str, kind: str, timeout: float = 60.0) -> FetchResult:
    """TCP/TLS fetch via requests (verifies cert chain by default)."""
    t0 = time.monotonic()
    try:
        import requests  # main dependency

        resp = requests.get(url, timeout=timeout, headers={"User-Agent": USER_AGENT})
        data = resp.content
        ok = resp.status_code == 200 and _payload_ok(data, kind)
        return FetchResult(
            ok=ok,
            kind=kind,
            url=url,
            transport="tcp",
            data=data if ok else b"",
            ms=(time.monotonic() - t0) * 1000,
            tls_verified=resp.url.startswith("https://"),
            error="" if ok else f"HTTP {resp.status_code}" + (
                "" if _payload_ok(data, kind) else " (payload rejected by magic check)"
            ),
            sha256=_sha256(data) if ok else "",
        )
    except Exception as e:  # connection reset is the CN-network norm
        return FetchResult(
            ok=False, kind=kind, url=url, transport="tcp",
            ms=(time.monotonic() - t0) * 1000, error=str(e)[:200],
        )


async def async_quic_fetch(
    url: str, kind: str, timeout: float = 60.0, range_from: int = 0
) -> FetchResult:
    """HTTP/3 single fetch — awaitable core (see :func:`quic_fetch`).

    range_from > 0 sends ``Range: bytes={range_from}-`` and accepts 206
    Partial Content — the resume primitive for interrupted transfers.
    """
    t0 = time.monotonic()
    try:
        from aioquic.h3.connection import H3_ALPN, H3Connection
        from aioquic.h3.events import DataReceived, HeadersReceived
        from aioquic.quic.configuration import QuicConfiguration
    except ImportError:
        return FetchResult(
            ok=False, kind=kind, url=url, transport="quic",
            ms=(time.monotonic() - t0) * 1000,
            error="aioquic unavailable — install with: pip install hfpclawer[quic]",
        )

    from urllib.parse import urlsplit

    from aioquic.asyncio.client import connect
    from aioquic.asyncio.protocol import QuicConnectionProtocol

    parts = urlsplit(url)
    # Generous receive windows: arXiv PDFs run 1-6 MB over UDP; the default
    # aioquic windows throttle large transfers badly.
    config = QuicConfiguration(
        is_client=True,
        alpn_protocols=H3_ALPN,
        max_data=32 * 1024 * 1024,
        max_stream_data=32 * 1024 * 1024,
    )
    config.verify_mode = 1  # ssl.CERT_REQUIRED — reject bad chains

    class _Client(QuicConnectionProtocol):
        """Minimal HTTP/3 client: drive one GET, collect full body."""

        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.http = H3Connection(self._quic)
            self.body = bytearray()
            self.status = 0
            self.finished = asyncio.Event()

        def quic_event_received(self, event) -> None:
            """Asyncio pump feeds QUIC events here — decode H3 frames."""
            for ev in self.http.handle_event(event):
                if isinstance(ev, HeadersReceived):
                    for h, v in ev.headers:
                        if h == b":status":
                            self.status = int(v.decode())
                elif isinstance(ev, DataReceived):
                    self.body.extend(ev.data)
                    if ev.stream_ended:
                        self.finished.set()

        def start_request(self) -> None:
            stream_id = self._quic.get_next_available_stream_id()
            headers = [
                (b":method", b"GET"), (b":scheme", b"https"),
                (b":authority", parts.netloc.encode()),
                (b":path", parts.path.encode()),
                (b"user-agent", USER_AGENT.encode()),
            ]
            if range_from > 0:
                headers.append((b"range", f"bytes={range_from}-".encode()))
            self.http.send_headers(
                stream_id, headers, end_stream=True,
            )
            self.transmit()

    async with connect(
        parts.hostname, parts.port or 443, configuration=config,
        create_protocol=_Client,
    ) as protocol:
        protocol.start_request()
        try:
            await asyncio.wait_for(protocol.finished.wait(), timeout=timeout)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            pass

        data = bytes(protocol.body)
        complete = protocol.finished.is_set()
        status_ok = protocol.status in (200, 206)  # 206 = partial range resume
        # Magic check only applies to a full-body GET (offset 0); a resumed
        # range chunk is mid-file and has no %PDF header by construction.
        payload_ok = _payload_ok(data, kind) if range_from == 0 else len(data) > 0
        ok = complete and status_ok and payload_ok
        return FetchResult(
            ok=ok,
            kind=kind,
            url=url,
            transport="quic",
            # Partial bytes are kept on failure too — resumable callers append
            # them to their .part file and resume via Range on the next round.
            data=data,
            ms=(time.monotonic() - t0) * 1000,
            tls_verified=True,  # CERT_REQUIRED chain check passed to reach here
            error=(
                ""
                if ok
                else f"HTTP {protocol.status or 'no-response'}"
                + ("" if complete else " (incomplete — timed out mid-transfer)")
            ),
            sha256=_sha256(data) if ok and range_from == 0 else "",
        )


def quic_fetch(
    url: str, kind: str, timeout: float = 60.0, range_from: int = 0
) -> FetchResult:
    """HTTP/3 (QUIC/UDP 443) fetch via aioquic — optional extra ``[quic]``.

    QUIC carries no TLS SNI plaintext to fingerprint, which is why this path
    survives where TCP is reset. Certificates are chain-verified with
    CERT_REQUIRED (handshake fails on mismatch). ``range_from > 0`` issues a
    Range request (resume primitive).
    """
    try:
        import aioquic  # noqa: F401  (optional extra — ImportError handled inside)
    except ImportError:
        return FetchResult(
            ok=False, kind="pdf", url=url, transport="quic",
            error="aioquic unavailable — install with: pip install hfpclawer[quic]",
        )
    return asyncio.run(async_quic_fetch(url, kind, timeout=timeout, range_from=range_from))


def quic_batch_fetch(
    paths: list[tuple[str, str]], timeout: float = 120.0
) -> list[FetchResult]:
    """HTTP/3 batch fetch — ONE connection, N concurrent streams.

    CN-network reality: each new QUIC connection pays handshake + congestion
    window ramp-up (arXiv over UDP measures ~100 KB/s ramp). Multiplexing many
    papers on one connection amortises the ramp across all streams — 3 PDFs
    (11.5MB + 1.4MB) completed within one window where per-paper connections
    each took 30-90s. Streams that error early (bad id / redirect) return
    their own failed FetchResult without blocking the rest.

    Args:
        paths: list of (arxiv_id, kind) — kinds map to /pdf/{id} and /src/{id}.
        timeout: per-call budget for the WHOLE batch (not per stream).
    """
    t0 = time.monotonic()
    try:
        from aioquic.asyncio.client import connect
        from aioquic.asyncio.protocol import QuicConnectionProtocol
        from aioquic.h3.connection import H3_ALPN, H3Connection
        from aioquic.h3.events import DataReceived, HeadersReceived
        from aioquic.quic.configuration import QuicConfiguration
    except ImportError:
        return [
            FetchResult(ok=False, kind=k, url=arxiv_url(a, k), transport="quic",
                        error="aioquic unavailable — pip install hfpclawer[quic]")
            for a, k in paths
        ]

    class _Batch(QuicConnectionProtocol):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.http = H3Connection(self._quic)
            self.bodies: dict[int, bytearray] = {}
            self.status: dict[int, int] = {}
            self.done: dict[int, asyncio.Event] = {}

        def quic_event_received(self, event) -> None:
            for ev in self.http.handle_event(event):
                sid = getattr(ev, "stream_id", None)
                if sid is None:
                    continue
                if isinstance(ev, HeadersReceived):
                    for h, v in ev.headers:
                        if h == b":status":
                            self.status[sid] = int(v.decode())
                elif isinstance(ev, DataReceived):
                    self.bodies.setdefault(sid, bytearray()).extend(ev.data)
                    if ev.stream_ended:
                        self.done.setdefault(sid, asyncio.Event()).set()

        def start(self, url: str) -> int:
            from urllib.parse import urlsplit

            parts = urlsplit(url)
            sid = self._quic.get_next_available_stream_id()
            self.http.send_headers(
                sid,
                [(b":method", b"GET"), (b":scheme", b"https"),
                 (b":authority", parts.netloc.encode()),
                 (b":path", parts.path.encode()),
                 (b"user-agent", USER_AGENT.encode())],
                end_stream=True,
            )
            self.done[sid] = asyncio.Event()
            return sid

    async def _run() -> list[FetchResult]:
        from urllib.parse import urlsplit

        first = urlsplit(arxiv_url(paths[0][0], paths[0][1]))
        host = first.hostname
        port = first.port or 443
        config = QuicConfiguration(
            is_client=True, alpn_protocols=H3_ALPN,
            max_data=64 * 1024 * 1024, max_stream_data=32 * 1024 * 1024,
        )
        config.verify_mode = 1  # CERT_REQUIRED

        async with connect(host, port, configuration=config,
                           create_protocol=_Batch) as protocol:
            urls = [arxiv_url(a, k) for a, k in paths]
            sids = [protocol.start(u) for u in urls]
            protocol.transmit()
            deadline = asyncio.get_running_loop().time() + timeout
            remaining = set(sids)
            while remaining and asyncio.get_running_loop().time() < deadline:
                for sid in [s for s in remaining if protocol.done[s].is_set()]:
                    remaining.discard(sid)
                if not remaining:
                    break
                await asyncio.sleep(0.2)

            results = []
            for sid, (aid, kind), url in zip(sids, paths, urls):
                data = bytes(protocol.bodies.get(sid, b""))
                complete = protocol.done[sid].is_set()
                st = protocol.status.get(sid, 0)
                ok = complete and st == 200 and _payload_ok(data, kind)
                results.append(FetchResult(
                    ok=ok, kind=kind, url=url, transport="quic",
                    data=data if ok else b"",
                    ms=(time.monotonic() - t0) * 1000,
                    tls_verified=True,
                    error=("" if ok else f"HTTP {st or 'no-response'}"
                           + ("" if complete else " (incomplete — batch deadline)")),
                    sha256=_sha256(data) if ok else "",
                ))
            return results

    try:
        return asyncio.run(_run())
    except Exception as e:  # connection-level failure — all streams failed
        return [
            FetchResult(ok=False, kind=k, url=arxiv_url(a, k), transport="quic",
                        error=str(e)[:200])
            for a, k in paths
        ]


def browser_hint(arxiv_id: str, kind: str) -> str:
    """Echo guidance when CLI transports are exhausted (no QUIC client)."""
    url = arxiv_url(arxiv_id, kind)
    if kind == "source":
        return (
            f"Hermes Agent 可用浏览器技能下载 tex 源码包:\n"
            f"  browser_navigate '{url}'  → 浏览器自动保存 arxiv.org/e-print/{arxiv_id}\n"
            f"(Chromium 走 QUIC 直连, 不受 TCP 重置影响)"
        )
    return (
        f"Hermes Agent 可用浏览器技能下载单篇 PDF:\n"
        f"  browser_navigate '{url}'  (Chromium 走 QUIC 直连)\n"
        f"或查 AlphaXiv: https://www.alphaxiv.org/abs/{arxiv_id}"
    )


def fetch_with_fallback(
    arxiv_id: str,
    kind: str = "pdf",
    timeout: float = 60.0,
    allow_quic: bool = True,
) -> FetchResult:
    """tcp -> quic -> hint. Returns the first success; on total failure a hint row."""
    url = arxiv_url(arxiv_id, kind)
    r = tcp_fetch(url, kind, timeout=timeout)
    if r.ok:
        return r
    if allow_quic:
        rq = quic_fetch(url, kind, timeout=min(timeout, 30.0))
        if rq.ok:
            return rq
    r.ms = max(r.ms, 0.0)
    hint = browser_hint(arxiv_id, kind)
    return FetchResult(
        ok=False, kind=kind, url=url, transport="hint",
        ms=r.ms, error=r.error, hint=hint,
    )


# ── Acquisition audit (append-only JSONL) ────────────────────────────────

def acquisition_log_path(data_dir: Optional[Path] = None) -> Path:
    base = data_dir or Path(__file__).resolve().parent.parent / "data"
    return base / "download_audit.jsonl"


def log_acquisition(row: dict, data_dir: Optional[Path] = None) -> Path:
    """Append one acquisition event (idempotent by (arxiv_id,kind,transport,ts))."""
    path = acquisition_log_path(data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
    return path


def scan_acquisitions(
    data_dir: Optional[Path] = None, min_batch: int = 2
) -> list[dict]:
    """Cross-batch/cross-transport content-integrity scan.

    MITM probe: the same (arxiv_id, kind) must have identical sha256 across
    every recorded acquisition. A differing hash = payload was swapped on a
    channel (or upstream changed the file) — flagged for review.
    """
    path = acquisition_log_path(data_dir)
    if not path.exists():
        return []
    by_paper: dict[tuple[str, str], dict] = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if row.get("event") != "acquisition" or not row.get("ok"):
                continue
            key = (row.get("arxiv_id", ""), row.get("kind", ""))
            h = row.get("sha256", "")
            if not key[0] or not h:
                continue
            cur = by_paper.setdefault(key, {"arxiv_id": key[0], "kind": key[1],
                                            "hashes": {}, "rows": []})
            cur["hashes"].setdefault(h, []).append(row)
            cur["rows"].append(row)
    alerts = []
    for (aid, kind), cur in by_paper.items():
        if len(cur["hashes"]) > 1:
            transports = [r["transport"] for r in cur["rows"]]
            alerts.append({
                "severity": "content-drift",
                "arxiv_id": aid,
                "kind": kind,
                "transports": sorted(set(transports)),
                "hash_count": len(cur["hashes"]),
                "detail": (
                    f"{aid} ({kind}) acquired with different sha256 across "
                    f"{sorted(set(transports))} — possible MITM swap or upstream change"
                ),
            })
    return alerts


# ── Resumable fetch (Range) + file integrity ─────────────────────────────

def file_sha256(path: Path) -> str:
    """sha256 of a file on disk — the integrity anchor for resumed files."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def fetch_resumable(
    arxiv_id: str,
    kind: str = "pdf",
    dest: Optional[Path] = None,
    timeout: float = 90.0,
    max_rounds: int = 5,
) -> FetchResult:
    """Resumable QUIC fetch — .part file + Range resume + sha256 integrity.

    Loop: append to ``<dest>.part`` until the HTTP/3 stream ends (each round
    carries its own timeout); on interruption the .part size becomes the next
    round's ``Range: bytes=N-`` offset. When the stream finally ends the full
    file is assembled — its sha256 is computed and returned as the audit hash
    (the integrity anchor for cross-channel MITM compare).

    URL mapping: kind=pdf -> /pdf/{id}, kind=source -> /src/{id} (tex bundle).
    """
    url = arxiv_url(arxiv_id, kind)
    if dest is None:
        base = Path.cwd()
        dest = base / f"{arxiv_id}{'.pdf' if kind == 'pdf' else '.tar.gz'}"
    part = dest.with_name(dest.name + ".part")
    t0 = time.monotonic()
    rounds = 0

    while rounds < max_rounds:
        rounds += 1
        offset = part.stat().st_size if part.exists() else 0
        r = quic_fetch(url, kind, timeout=timeout, range_from=offset)
        if r.ok:
            # Complete chunk (200 full body or 206 partial-to-end)
            with open(part, "ab") as f:
                f.write(r.data)
            final_hash = file_sha256(part)
            part.rename(dest)
            if offset == 0 and r.sha256 and final_hash != r.sha256:
                # Full-body hash mismatch — payload corrupted in transit.
                dest.unlink(missing_ok=True)
                return FetchResult(
                    ok=False, kind=kind, url=url, transport="quic",
                    ms=(time.monotonic() - t0) * 1000,
                    tls_verified=True,
                    error="sha256 mismatch: transferred payload corrupted",
                )
            return FetchResult(
                ok=True, kind=kind, url=url, transport="quic",
                data=b"",  # content lives on disk (dest); hash is the handle
                ms=(time.monotonic() - t0) * 1000,
                tls_verified=True,
                sha256=final_hash,
            )
        # Failed round: keep whatever partial bytes arrived (timeout mid-body
        # keeps them in r.data), then resume from the grown .part size.
        if r.data:
            with open(part, "ab") as f:
                f.write(r.data)
            continue
        if "incomplete" in r.error or offset > 0:
            continue
        return r  # hard failure (no progress, not resumable) — surface it

    return FetchResult(
        ok=False, kind=kind, url=url, transport="quic",
        ms=(time.monotonic() - t0) * 1000,
        tls_verified=True,
        error=f"resume exhausted after {max_rounds} rounds ({part})",
    )
