#!/usr/bin/env python3
"""cron_round.py -- reusable arXiv round runner: axis query -> store diff -> ingest -> regression.

Why this exists
---------------
The per-round ingest scripts (`cron_round_<date>.py`) were one-shots. Each carried its own copy of
the metadata, or its own hand-rolled arXiv client, and its own idea of what "already filed" means.
Three defects came out of that, all measured on 2026-10-10:

1. **id-form split.** `2610.06986` and `2610.06986v1` are the *same* paper but compare unequal under
   exact string matching, so a dedup probe written in one form silently missed the other. The store
   ended up holding both: a stray row titled `x` sitting next to the real `OpenDiscoveryTrace`
   entry for `2609.09203` / `2609.09203v1`.
2. **no shared diff.** "Which candidates are new" was recomputed by hand every round, against
   nothing reproducible.
3. **a private HTTP client.** One round re-implemented the arXiv call with `CERT_NONE`, which skips
   TLS verification for no benefit; `hfpapers.arxiv_lookup._http_get` already solves the real
   problem there (the `406` edge fingerprint) without weakening TLS.

So: the genuinely round-specific parts (the axes, the picks, the regression id) stay as
**arguments**, and everything else is delegated to existing modules -- `arxiv_lookup` for HTTP,
pacing and feed parsing, and `paper_store` (via its **public** methods only) for identity and
ingest.

Contract
--------
* **Idempotent.** Re-running with the same arguments ingests nothing new and still passes.
* **Normalised identity.** Comparison is on the bare `YYMM.NNNNN` form, so a stored `vN` variant
  counts as *already filed*, never as a second paper.
* **Fails loudly.** The exit status is non-zero when an assertion breaks; `--dry-run` never writes.
* **Offline-testable.** Everything except `query_axis` is pure and covered by
  `tests/test_cron_round.py`.

Usage
-----
    python3 scripts/cron_round.py \\
        --source cron-2026-10-11-round11 \\
        --axis 'all:"AI for science" AND all:agent' \\
        --pick 2610.06986 \\
        --dedup-regression 2610.06986v1 \\
        --json-out /tmp/round11.json

Exit codes: 0 ok / 1 assertion violated / 2 usage or environment error.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.parse
from collections.abc import Callable, Iterable
from pathlib import Path

# Bare arXiv id: YYMM.NNNNN -- four digits, a dot, four or five digits. Older schemes are out of
# scope; anything else is rejected rather than guessed at.
ARXIV_ID_RE = re.compile(r"^(?P<bare>\d{4}\.\d{4,5})(?:v(?P<version>\d+))?$")

# Characters that must survive percent-encoding inside a `search_query`: the field-prefix colon,
# the boolean operators' plus signs, and grouping parentheses. Quotes are deliberately NOT here --
# they are encoded to `%22`, matching `arxiv_lookup.build_api_url`, which is the convention the API
# edge was measured to accept.
_QUERY_SAFE = "+:()."

# Version suffixes probed when asking the store whether a bare id is already filed. arXiv has never
# issued a v10 in practice, and probing a bounded set keeps this on the public per-id API.
_MAX_PROBED_VERSION = 9

API = "https://export.arxiv.org/api/query"


class UsageError(Exception):
    """Bad input or a broken environment; mapped to exit code 2."""


# ---------------------------------------------------------------------------------------- pure logic


def normalize_arxiv_id(raw: str) -> str:
    """Return the canonical bare form of an arXiv id, dropping any `vN` suffix.

    Raises `ValueError` for anything that is not an arXiv id: a mistyped id must never be able to
    enter the store as a fresh record, which is exactly the defect this function exists to prevent.

    >>> normalize_arxiv_id("2610.06986v1")
    '2610.06986'
    """
    match = ARXIV_ID_RE.match((raw or "").strip())
    if not match:
        raise ValueError(f"not an arXiv id: {raw!r}")
    return match.group("bare")


def build_axis_url(query: str, max_results: int) -> str:
    """Build a `search_query` URL that keeps arXiv's operators literal.

    Do **not** `urlencode()` the whole query: that turns the `+` of `A+AND+B` into `%2B`, which the
    API then reads as a different, empty query. Only characters outside `_QUERY_SAFE` are encoded
    here, so `all:"AI for science" AND all:agent` reaches the API intact.
    """
    if not (query or "").strip():
        raise ValueError("empty axis query")
    encoded = urllib.parse.quote(query.strip(), safe=_QUERY_SAFE)
    return (
        f"{API}?search_query={encoded}"
        f"&sortBy=submittedDate&sortOrder=descending&max_results={int(max_results)}"
    )


def build_idlist_url(ids: list[str], max_results: int | None = None) -> str:
    """`id_list=` form of the API: the only way to get metadata for an explicitly picked paper.

    `search_query=` cannot express "give me exactly these ids", and the runner used to hand
    `--pick` ids to `ensure_paper` with **no metadata at all**: measured 2026-10-17, three picks
    landed as rows with `title=''`, empty abstract and `year=0` — invisible to every later
    title/year query, i.e. the same class of orphan row the year backfill was meant to end.
    """
    clean = [bare.strip() for bare in (ids or []) if bare and bare.strip()]
    if not clean:
        raise ValueError("empty id_list")
    window = max(int(max_results or 0), len(clean))
    return f"{API}?id_list={','.join(clean)}&max_results={window}"


def fetch_by_ids(ids: list[str], pacing) -> list[dict]:
    """Metadata rows (`id`/`title`/`published`/`abstract`) for explicit ids."""
    if not ids:
        return []
    from hfpapers.arxiv_lookup import _http_get, parse_feed

    url = build_idlist_url(ids)
    pacing.wait()
    status, body = _http_get(url, timeout=45.0)
    pacing.note(len(body))
    if status != 200 or not body:
        raise UsageError(f"id_list query failed (status={status}, bytes={len(body)})")
    text = body.decode("utf-8", "ignore")
    return merge_rows_with_summaries(parse_feed(text), extract_summaries(text))


def year_from_published(published: str) -> int:
    """`2026-10-08` -> `2026`; anything else -> `0`, which is the store's "not filled" value."""
    match = re.match(r"^(\d{4})-", (published or "").strip())
    return int(match.group(1)) if match else 0


def extract_summaries(xml_text: str) -> list[str]:
    """Pull one abstract per `<entry>`, in feed order, whitespace-collapsed.

    `arxiv_lookup.parse_feed` deliberately returns only `{id,title,published,categories}` (it serves
    the title-lookup path), so the abstract is taken here and merged positionally. Without this the
    store would gain records with no abstract, which is a regression against the one-shot scripts.
    """
    out: list[str] = []
    for block in re.findall(r"<summary>([\s\S]*?)</summary>", xml_text or ""):
        out.append(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", block)).strip())
    return out


def merge_rows_with_summaries(rows: list[dict], summaries: list[str]) -> list[dict]:
    """Zip feed rows with abstracts positionally; a count mismatch degrades to empty abstracts."""
    aligned = len(rows) == len(summaries)
    merged: list[dict] = []
    for position, row in enumerate(rows):
        enriched = dict(row)
        enriched["abstract"] = summaries[position] if aligned else ""
        merged.append(enriched)
    return merged


def stored_year_missing(store, sf_id: int) -> bool:
    """True when the record exists but carries no year (the store's "not filled" value is 0)."""
    record = store.get_paper_by_id(sf_id)
    return not getattr(record, "year", 0)


def select_new(
    candidates: Iterable[str], is_filed: Callable[[str], bool]
) -> tuple[list[str], list[str]]:
    """Split candidates into `(new, already_filed)`, comparing on the normalised bare id.

    `is_filed` is injected so this stays pure and testable; both sides are returned so the caller
    can report what it skipped. Candidate order is preserved, which is how the axis ranking
    (newest first) survives into the picks.
    """
    new: list[str] = []
    filed: list[str] = []
    seen: set[str] = set()
    for raw in candidates:
        bare = normalize_arxiv_id(raw)
        if bare in seen:
            continue
        seen.add(bare)
        (filed if is_filed(bare) else new).append(bare)
    return new, filed


def evaluate_regression(probes: list[dict]) -> list[str]:
    """Return a message per dedup probe that came back `is_new=True`.

    A probe re-posts an already-filed id, so the only correct answer is `is_new=False`. `True` means
    the dedup path is broken -- the failure the rounds kept discovering by hand, after the fact.
    """
    return [
        f"dedup regression failed: {probe['arxiv_id']} returned is_new=True (expected False)"
        for probe in probes
        if probe.get("is_new")
    ]


def find_stored_form(store, bare: str) -> str | None:
    """The raw stored form of `bare`, if the store holds it under any version suffix.

    Probes the bare form and `v1..v_MAX_PROBED_VERSION` through `get_paper_by_identifier`, so this
    needs no private connection and cannot be defeated by the version-form split described above.
    """
    for candidate in [bare] + [f"{bare}v{k}" for k in range(1, _MAX_PROBED_VERSION + 1)]:
        if store.get_paper_by_identifier("arxiv", candidate) is not None:
            return candidate
    return None


def resolve_ingest_id(store, bare: str) -> str:
    """The form the store already holds `bare` under, or `bare` itself when it is absent.

    `select_new` already probes version suffixes before calling something "new", but `ingest_one`
    used to hand `ensure_paper` the bare id unconditionally. Measured on 2026-10-16: re-posting
    `2610.08691` -- filed since round 8 as `2610.08691v1` -- wrote a *second* paper row (empty title,
    `year=0`) plus a second identifier. That is the id-form split this module's docstring says it
    exists to prevent, and the trigger was the dedup probe itself: the probe is supposed to discover
    a broken dedup path, not to manufacture a duplicate while doing it.
    """
    return find_stored_form(store, bare) or bare


def audit_duplicated_forms(store) -> dict[str, list[str]]:
    """Bare ids held under more than one raw form -- the latent duplicate-paper signal.

    Opt-in: it walks every paper through the public API, which is fine for an audit and too slow
    for the hot path. Values that are not arXiv ids at all are skipped; those are reported by the
    store's own audit tooling.
    """
    index: dict[str, list[str]] = {}
    for record in store.get_all_papers():
        for identifier in store.get_identifiers(record.sf_id):
            if identifier.id_type != "arxiv":
                continue
            try:
                bare = normalize_arxiv_id(identifier.id_value)
            except ValueError:
                continue
            index.setdefault(bare, []).append(identifier.id_value)
    return {bare: forms for bare, forms in index.items() if len(forms) > 1}


# ------------------------------------------------------------------------------------- network glue


def query_axis(query: str, max_results: int, pacing) -> list[dict]:
    """Fetch one axis and return rows carrying `arxiv_id`/`title`/`published`/`abstract`."""
    from hfpapers.arxiv_lookup import _http_get, parse_feed

    url = build_axis_url(query, max_results)
    pacing.wait()
    status, body = _http_get(url, timeout=45.0)
    pacing.note(len(body))
    if status != 200 or not body:
        raise UsageError(f"axis query failed (status={status}, bytes={len(body)}): {query[:60]}")
    text = body.decode("utf-8", "ignore")
    rows = merge_rows_with_summaries(parse_feed(text), extract_summaries(text))
    return [row for row in rows if row.get("id")]


# ----------------------------------------------------------------------------------------- ingest


def ingest_one(store, candidate: dict, source: str) -> dict:
    """Ensure one paper exists, then backfill `year` while the store still has none.

    `ensure_paper` takes no `year` argument, so the year is a separate targeted update; leaving it
    at 0 is what makes most of this store unusable for any year-based analysis. Two further points,
    both measured rather than assumed:

    * the id handed to `ensure_paper` is the **stored** form when one exists, so a re-post of a paper
      held as `NNNN.NNNNNv1` dedups instead of forking a duplicate row (see `resolve_ingest_id`);
    * the year is filled whenever the stored record has none -- not only on a fresh insert. A first
      insert whose metadata arrived without `published` would otherwise stay `year=0` for ever, and
      re-posting it (the dedup probe) is exactly when the fix becomes free.
    """
    from hfpapers.paper_store import ensure_paper

    bare = normalize_arxiv_id(candidate["arxiv_id"])
    sf_id, is_new = ensure_paper(
        resolve_ingest_id(store, bare),
        title=candidate.get("title", ""),
        source=source,
        abstract=candidate.get("abstract", ""),
        venue=candidate.get("venue", "arXiv"),
        skip_crossref=True,
        imported_via=source,
    )
    year = year_from_published(candidate.get("published", ""))
    if year and stored_year_missing(store, sf_id):
        store.update_paper(sf_id, year=year)
    return {"arxiv_id": bare, "sf_id": sf_id, "is_new": bool(is_new), "year": year}


# ------------------------------------------------------------------------------------------- CLI


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Reusable arXiv round runner")
    parser.add_argument("--source", required=True,
                        help="provenance label, e.g. cron-2026-10-11-round11")
    parser.add_argument("--axis", action="append", default=[],
                        help="arXiv search_query, operators kept literal (repeatable)")
    parser.add_argument("--pick", action="append", default=[],
                        help="explicit arXiv id, taken as-is (repeatable)")
    parser.add_argument("--dedup-regression", action="append", default=[],
                        help="already-filed id to re-post; must return is_new=False (repeatable)")
    parser.add_argument("--max-results", type=int, default=20, help="per axis (default 20)")
    parser.add_argument("--dry-run", action="store_true", help="report only; never write")
    parser.add_argument("--audit-forms", action="store_true",
                        help="also scan the store for ids held under several forms (slow)")
    parser.add_argument("--json-out", default="", help="write the summary JSON here")
    return parser.parse_args(argv)


def _run(args: argparse.Namespace) -> tuple[dict, int]:
    from hfpapers.arxiv_lookup import Pacing
    from hfpapers.paper_store import get_store, store_stats

    for raw in list(args.pick) + list(args.dedup_regression):
        normalize_arxiv_id(raw)  # raises ValueError before anything is written
    if not args.axis and not args.pick:
        raise UsageError("nothing to do: pass at least one --axis or --pick")

    pacing = Pacing()
    store = get_store()
    before = store_stats()
    summary: dict = {
        "source": args.source,
        "axes": args.axis,
        "candidates": [],
        "already_filed": [],
        "ingested": [],
        "dedup_regression": [],
        "violations": [],
        "duplicated_forms": audit_duplicated_forms(store) if args.audit_forms else {},
        "dry_run": bool(args.dry_run),
    }

    # 1. Gather candidates once, keeping each axis row's metadata alongside its id.
    rows: list[dict] = []
    for query in args.axis:
        rows.extend(query_axis(query, args.max_results, pacing))
    metadata = {row["id"]: row for row in rows}
    picks = [normalize_arxiv_id(raw) for raw in args.pick]
    missing = [bare for bare in dict.fromkeys(picks) if bare not in metadata]
    if missing:
        rows.extend(fetch_by_ids(missing, pacing))
        metadata = {row["id"]: row for row in rows}
        unfetched = [bare for bare in missing if bare not in metadata]
        if unfetched:
            # Fail loudly instead of writing title-less rows: an empty shell is worse than a
            # missing paper, because no later query on title/year can find it again.
            raise UsageError(f"no arXiv metadata for picks: {', '.join(unfetched)}")
    candidates = [normalize_arxiv_id(row["id"]) for row in rows] + picks

    is_filed = lambda bare: find_stored_form(store, bare) is not None  # noqa: E731
    new_ids, filed_ids = select_new(candidates, is_filed)
    summary["candidates"] = candidates
    summary["already_filed"] = filed_ids

    if args.dry_run:
        summary["would_ingest"] = new_ids
        summary["store"] = {"before": before, "after": before}
        return summary, 0

    # 2. Ingest the new ids, carrying metadata across from the axis rows where we have it.
    for bare in new_ids:
        payload = dict(metadata.get(bare, {}))
        payload["arxiv_id"] = bare
        summary["ingested"].append(ingest_one(store, payload, args.source))

    # 3. Dedup regression: a re-posted, already-filed id must come back is_new=False.
    for raw in args.dedup_regression:
        bare = normalize_arxiv_id(raw)
        result = ingest_one(store, {"arxiv_id": bare}, args.source)
        summary["dedup_regression"].append({"arxiv_id": bare, "is_new": result["is_new"]})

    summary["violations"] = evaluate_regression(summary["dedup_regression"])
    summary["store"] = {"before": before, "after": store_stats()}
    return summary, 1 if summary["violations"] else 0


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        summary, code = _run(args)
    except UsageError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    text = json.dumps(summary, ensure_ascii=False, indent=2)
    if args.json_out:
        Path(args.json_out).write_text(text + "\n", encoding="utf-8")
    print(text)
    for violation in summary["violations"]:
        print(f"VIOLATION: {violation}", file=sys.stderr)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
