# -*- coding: utf-8 -*-
"""Title → arXiv ID reverse lookup: gates, pacing, and the fallback contract.

Every rule in `hfpapers/arxiv_lookup.py` is pinned here by the failure it prevents (all measured
2026-09-23): HTTPS-only + 0-byte throttling, the `+` → `%2B` query mangling, and — most expensive —
a *plausible neighbour* title being accepted as the answer.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from hfpapers.arxiv_lookup import (  # noqa: E402
    Pacing,
    build_api_url,
    lookup_title,
    lookup_titles,
    normalize_title,
    parse_feed,
    request_headers,
    title_match,
    title_ratio,
)

FEED = """<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom">
 <entry><id>http://arxiv.org/abs/2609.18094v2</id>
  <title>Agora: Git as Shared Memory for Collective AutoResearch</title>
  <published>2026-09-16T00:00:00Z</published>
  <category term="cs.LG"/><category term="cs.AI"/></entry>
 <entry><id>http://arxiv.org/abs/2602.14117v3</id>
  <title>Toward Autonomous O-RAN: A Multi-Scale Agentic AI Framework</title>
  <published>2026-02-15T00:00:00Z</published>
  <category term="cs.NI"/></entry>
</feed>"""

EMPTY_FEED = """<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom"></feed>"""


class TestGates:
    def test_normalize_strips_case_and_punctuation(self):
        assert normalize_title("Agora: Git as Shared Memory!") == "agora git as shared memory"
        assert normalize_title("  Multiple   spaces\n") == "multiple spaces"

    def test_exact_after_normalization(self):
        m = title_match("CodeMidas: Scaling Agentic Coding RL Environments from Code Itself",
                        "codemidas scaling agentic coding rl environments from code itself.")
        assert m.ok and m.reason == "exact" and m.ratio == 1.0

    def test_containment_accepted_for_long_titles(self):
        m = title_match("Generalized Agent Iteration: One Formal Framework for Iterative Policy Improvement and Recursive Self-improvement",
                        "Generalized Agent Iteration: One Formal Framework for Iterative Policy Improvement")
        assert m.ok and m.reason == "prefix"

    def test_plausible_neighbour_is_rejected(self):
        """The expensive one: a real candidate that is a *different* paper."""
        m = title_match("Towards grounded autonomous research: an end-to-end LLM mini research loop",
                        "DriveE2E: Closed-Loop Benchmark for End-to-End Autonomous Driving")
        assert not m.ok, m
        assert m.reason == "below-threshold" and m.ratio < 0.60

    def test_ratio_gate_accepts_a_reworded_title(self):
        m = title_match("Agora: Git as Shared Memory for Collective AutoResearch",
                        "Git Agora: Git as Shared Memory for Collective AutoResearch")
        assert m.ok

    def test_empty_input_is_not_a_match(self):
        assert not title_match("", "anything").ok
        assert title_ratio("x", "y") < 0.60


class TestUrl:
    def test_phrase_is_encoded_and_prefix_is_literal(self):
        url = build_api_url("Git as Shared Memory")
        assert url.startswith("https://export.arxiv.org/api/query?search_query=ti:%22")
        assert "%22" in url and "max_results=3" in url
        assert " " not in url, "spaces must be %20"

    def test_colon_inside_a_title_is_encoded(self):
        """Measured: a raw `:` in the phrase earns HTTP 406; `%3A` is fine."""
        url = build_api_url("Agora: Git as Shared Memory")
        phrase = url.split("search_query=ti:%22", 1)[1].split("%22", 1)[0]
        assert ":" not in phrase and "%3A" in phrase

    def test_quotes_in_title_do_not_break_the_query(self):
        url = build_api_url('Weird "Quoted" Title')
        assert url.count("%22") == 2, url

    def test_long_titles_are_truncated(self):
        assert "max_results=5" in build_api_url("A" * 400, max_results=5)


class TestHeaders:
    def test_accept_header_is_sent(self):
        """Measured: the API answers 406 without `Accept` — curl hides this, urllib does not."""
        h = request_headers()
        assert "Accept" in h and h["Accept"]
        assert h.get("User-Agent")


class TestFeed:
    def test_parses_entries(self):
        rows = parse_feed(FEED)
        assert [r["id"] for r in rows] == ["2609.18094", "2602.14117"]
        assert rows[0]["title"].startswith("Agora")
        assert rows[0]["published"] == "2026-09-16"
        assert rows[0]["categories"] == ["cs.LG", "cs.AI"]

    def test_empty_and_garbage_are_empty(self):
        assert parse_feed(EMPTY_FEED) == []
        assert parse_feed("not xml at all") == []


class TestPacing:
    def test_min_interval_between_calls(self):
        slept, now = [], [0.0]

        def fake_sleep(s):
            slept.append(round(s, 2))
            now[0] += s

        p = Pacing(min_interval=3.0, sleep=fake_sleep, clock=lambda: now[0])
        assert p.wait() == 0.0            # first call is free
        now[0] += 1.0
        assert p.wait() == 2.0            # tops up to the interval
        assert slept == [2.0]

    def test_zero_byte_response_backs_off_and_escalates(self):
        slept, now = [], [0.0]

        def fake_sleep(s):
            slept.append(round(s, 2))
            now[0] += s

        p = Pacing(min_interval=0.0, backoff=(5.0, 15.0), sleep=fake_sleep, clock=lambda: now[0])
        assert p.note(0) == "blocked" and p.blocked_events == 1
        assert p.wait() == 5.0
        p.note(0)
        assert p.wait() == 15.0           # escalates
        assert p.note(4096) == "ok"       # a real answer resets the level
        assert p.wait() == 0.0


class TestLookup:
    def test_found_reports_the_gate_that_accepted_it(self):
        r = lookup_title("Agora: Git as Shared Memory for Collective AutoResearch", fetch=lambda u: (200, FEED.encode()))
        assert r.found and r.arxiv_id == "2609.18094" and r.reason in ("exact", "ratio", "prefix")
        assert r.categories == ["cs.LG", "cs.AI"]

    def test_candidates_below_threshold_are_not_accepted(self):
        r = lookup_title("Towards grounded autonomous research", fetch=lambda u: (200, FEED.encode()))
        assert not r.found and r.reason == "below-threshold" and r.candidates == 2

    def test_no_candidate_is_distinct_from_blocked(self):
        assert lookup_title("Nothing Here", fetch=lambda u: (200, EMPTY_FEED.encode())).reason == "no-candidate"
        r = lookup_title("Nothing Here", fetch=lambda u: (0, b""))
        assert r.reason == "blocked" and r.candidates == 0

    def test_batch_keeps_order_and_shares_one_pacing(self):
        calls = []

        def fetch(url):
            calls.append(url)
            return 200, FEED.encode()

        pacing = Pacing(min_interval=0.0, sleep=lambda s: None)
        out = lookup_titles(["Agora: Git as Shared Memory for Collective AutoResearch", "Toward Autonomous O-RAN"], fetch=fetch, pacing=pacing)
        assert len(out) == 2 and len(calls) == 2
        assert "Agora" in out[0].title and "O-RAN" in out[1].title
        assert pacing.blocked_events == 0
