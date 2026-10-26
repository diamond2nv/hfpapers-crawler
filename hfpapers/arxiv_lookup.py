#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Title → arXiv ID reverse lookup — one paced, fallback-aware path for every caller.

Why this module exists
----------------------
The reverse-lookup recipe used to live in agent prose (``curl`` + a ``ti:`` query). It failed in
four predictable, *mechanical* ways (all measured 2026-09-23), so the rules live here once instead
of being re-derived every session:

1. **HTTPS only** — ``http://export.arxiv.org`` answers 301; a client that does not follow redirects
   sees a **0-byte** body, which looks exactly like "no such paper".
2. **Burst throttling** — ~40 calls in a few minutes earn a 0-byte response; the caller must slow
   down instead of concluding the paper does not exist.
3. **Query mangling** — ``urllib.parse.quote()`` encodes ``+`` as ``%2B``, turning the ``+AND+``
   operator into a literal plus and silently matching nothing.
4. **Fuzzy false positives** — the closest title match can be a *different* paper (measured: a search
   for "Towards grounded autonomous research" returned an autonomous-driving benchmark), so a
   candidate is only accepted through an explicit two-stage gate.

Layers
------
``normalize_title`` / ``title_match``   the gates: exact lowercase-normalised equality, then ratio
``Pacing``                              min interval + 0-byte detection with escalating backoff
``build_api_url`` / ``parse_feed``      the HTTPS API path (the only reliable metadata channel)
``lookup_title`` / ``lookup_titles``    one paper / a paced batch, each returning a *reason*
The abs page is a second opinion only: it confirms a title, it does not search.
"""

from __future__ import annotations

import difflib
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Callable

API = "https://export.arxiv.org/api/query"
ABS = "https://arxiv.org/abs/"
MIN_INTERVAL = 3.0                  # arXiv API etiquette: >=3s between calls
BLOCK_BACKOFF = (5.0, 15.0, 45.0)   # escalating sleeps after a 0-byte (throttled) response
TITLE_THRESHOLD = 0.60              # ratio floor; the equality gate runs first
USER_AGENT = "hfpclawer-lookup/1 (+https://github.com/diamond2nv/hfpapers-crawler)"

_PUNCT = re.compile(r"[^\w\s]+", re.UNICODE)
_WS = re.compile(r"\s+")


# ── the two gates ──────────────────────────────────────────────────────────────

def normalize_title(title: str) -> str:
    """Lowercase, drop punctuation, collapse whitespace — the gate against case/typography noise."""
    return _WS.sub(" ", _PUNCT.sub(" ", (title or "").lower())).strip()


def title_ratio(a: str, b: str) -> float:
    """Similarity of two titles after normalisation (0.0–1.0)."""
    return difflib.SequenceMatcher(None, normalize_title(a), normalize_title(b)).ratio()


@dataclass
class Match:
    ok: bool
    ratio: float
    reason: str  # exact | prefix | ratio | below-threshold


def title_match(target: str, candidate: str, threshold: float = TITLE_THRESHOLD) -> Match:
    """Two-stage gate: (1) exact match after normalisation, (2) containment, (3) ratio floor.

    Stage (1) is what makes the common case cheap and unambiguous; the ratio is only trusted above
    ``threshold`` because a *plausible* neighbour title is the failure mode we measured.
    """
    t, c = normalize_title(target), normalize_title(candidate)
    if not t or not c:
        return Match(False, 0.0, "below-threshold")
    if t == c:
        return Match(True, 1.0, "exact")
    # Containment is trusted only when the contained side is a *phrase* (>= 3 words). A character
    # threshold was tried first and rejected a legitimate short query ("Toward Autonomous O-RAN",
    # 4 words / 22 chars) while a fragment like "agora" must not be accepted on containment alone.
    shorter = t if len(t) <= len(c) else c
    if (t in c or c in t) and len(shorter.split()) >= 3:
        return Match(True, 1.0, "prefix")
    ratio = title_ratio(target, candidate)
    return Match(ratio >= threshold, round(ratio, 3), "ratio" if ratio >= threshold else "below-threshold")


# ── pacing: min interval + block detection ─────────────────────────────────────

class Pacing:
    """Call pacing for the arXiv API.

    Two behaviours, both measured: keep at least ``min_interval`` between calls, and treat a 0-byte
    response as *blocked* (throttled/reset) — sleeping an escalating ``backoff`` before the next one
    instead of re-asking immediately (the burst is what caused it).
    """

    def __init__(
        self,
        min_interval: float = MIN_INTERVAL,
        backoff: tuple[float, ...] = BLOCK_BACKOFF,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.min_interval = min_interval
        self.backoff = backoff
        self._sleep = sleep
        self._clock = clock
        self._last: float | None = None
        self.blocked_events = 0
        self._block_level = 0

    def wait(self) -> float:
        """Sleep as needed before the next call; returns the seconds slept."""
        waited = 0.0
        if self._last is not None:
            gap = self.min_interval - (self._clock() - self._last)
            if gap > 0:
                self._sleep(gap)
                waited += gap
        if self._block_level:
            pause = self.backoff[min(self._block_level - 1, len(self.backoff) - 1)]
            self._sleep(pause)
            waited += pause
        self._last = self._clock()
        return round(waited, 3)

    def note(self, body_len: int) -> str:
        """Record a response. A 0-byte body means throttled/reset, not "no results"."""
        if body_len <= 0:
            self.blocked_events += 1
            self._block_level = min(self._block_level + 1, len(self.backoff))
            return "blocked"
        self._block_level = 0
        return "ok"


# ── the HTTPS API path ────────────────────────────────────────────────────────

def build_api_url(title: str, max_results: int = 3) -> str:
    """Title query URL — the phrase is percent-encoded, the field prefix stays literal.

    Two measured rules live here:

    * **never** ``urllib.parse.quote()`` the whole query with defaults — it turns the ``+`` operator
      into ``%2B`` (and with ``+AND+`` queries that silently matches nothing);
    * encode the whole title (colons, quotes, spaces → ``%XX``) and assemble the literal ``ti:``
      prefix around it — leaving raw punctuation inside a phrase is the kind of thing that trips the
      API's edge for some clients (see ``_http_get`` for the measured client difference).
    """
    clean = (title or "").replace('"', " ").strip()[:160]  # keep exactly one quoted phrase
    inner = urllib.parse.quote(clean, safe="")  # colons/spaces/quotes inside -> %XX
    return f"{API}?search_query=ti:%22{inner}%22&max_results={int(max_results)}"


def _group(pattern: str, text: str, flags: int = 0) -> str:
    """First capture group of ``pattern`` in ``text``, or "" — never ``None``."""
    match = re.search(pattern, text, flags)
    return (match.group(1) if match else "") or ""


def parse_feed(xml_text: str) -> list[dict]:
    """Parse an arXiv API Atom feed into ``{id,title,published,categories}`` rows."""
    rows: list[dict] = []
    for entry in re.findall(r"<entry>(.*?)</entry>", xml_text or "", re.DOTALL):
        ident = _group(r"<id>http://arxiv\.org/abs/([^<]+)</id>", entry)
        if not ident:
            continue
        title = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", _group(r"<title>([\s\S]*?)</title>", entry, re.DOTALL))).strip()
        rows.append({
            "id": ident.split("v")[0],
            "title": title,
            "published": _group(r"<published>(\d{4}-\d\d-\d\d)", entry),
            "categories": re.findall(r'<category term="([^"]+)"', entry),
        })
    return rows


def request_headers() -> dict:
    """Headers the arXiv API needs, plus the one the edge appears to dislike missing.

    Measured 2026-09-23: a bare ``urllib`` request (no ``Accept``) earned **406 Not Acceptable**
    for one query while ``curl`` (which sends ``Accept: */*``) got 200. Send both explicitly.
    """
    return {"User-Agent": USER_AGENT, "Accept": "application/atom+xml, */*"}


def _http_get(url: str, timeout: float = 30.0) -> tuple[int, bytes]:
    """GET with the client that actually passes the API's edge. Returns ``(status, body)``.

    **Use ``requests`` first, ``urllib`` only as a fallback** — measured 2026-09-23: for a longer
    ``ti:`` query the very same URL answers **406 for urllib** (any UA/``Accept`` combination) while
    ``requests`` and ``curl`` get 200. That is an edge/WAF fingerprint difference, not a bad query,
    so the client choice is a correctness concern and not a style preference.

    ``(0, b"")`` means the transport failed; a 4xx/5xx surfaces as its status so callers can tell
    "the API refused this" from "the network dropped it".
    """
    headers = request_headers()
    try:
        import requests  # a core dependency; kept inside so gevent-free installs still work

        resp = requests.get(url, headers=headers, timeout=timeout)
        return resp.status_code, resp.content
    except Exception:  # noqa: BLE001 — fall through to urllib (transport-level failure or no requests)
        pass
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 (fixed https hosts)
            return resp.status, resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, b""
    except Exception:  # noqa: BLE001
        return 0, b""


# ── the public lookup ─────────────────────────────────────────────────────────

@dataclass
class LookupResult:
    query: str
    arxiv_id: str = ""
    title: str = ""
    published: str = ""
    categories: list[str] = field(default_factory=list)
    ratio: float = 0.0
    reason: str = ""            # exact | prefix | ratio | below-threshold | no-candidate | blocked
    candidates: int = 0

    @property
    def found(self) -> bool:
        return bool(self.arxiv_id)


def lookup_title(
    title: str,
    *,
    fetch: Callable[[str], tuple[int, bytes]] = _http_get,
    pacing: Pacing | None = None,
    threshold: float = TITLE_THRESHOLD,
    max_results: int = 3,
) -> LookupResult:
    """Resolve one title to an arXiv ID, or say *why* it could not.

    ``reason`` is the contract: ``blocked`` (throttled — retry later), ``no-candidate`` (the API
    answered but had nothing), ``below-threshold`` (candidates existed, none matched), or the gate
    that accepted it (``exact`` / ``prefix`` / ``ratio``).
    """
    pacing = pacing or Pacing()
    res = LookupResult(query=title)
    pacing.wait()
    status, body = fetch(build_api_url(title, max_results=max_results))
    state = pacing.note(len(body))
    if state == "blocked" or status == 0:
        res.reason = "blocked"
        return res
    rows = parse_feed(body.decode("utf-8", errors="ignore"))
    res.candidates = len(rows)
    if not rows:
        res.reason = "no-candidate"
        return res
    best, best_match = None, Match(False, 0.0, "below-threshold")
    for row in rows:
        m = title_match(title, row["title"], threshold)
        if m.ratio > best_match.ratio or (m.ok and not best_match.ok):
            best, best_match = row, m
    res.ratio, res.reason = best_match.ratio, best_match.reason
    if best and best_match.ok:
        res.arxiv_id, res.title = best["id"], best["title"]
        res.published, res.categories = best["published"], best["categories"]
    return res


def lookup_titles(titles: list[str], **kwargs) -> list[LookupResult]:
    """Paced batch: one result per input, in order. Shares one ``Pacing`` unless given one."""
    pacing = kwargs.pop("pacing", None) or Pacing()
    return [lookup_title(t, pacing=pacing, **kwargs) for t in titles]
