#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""cli_zotero.py — hfpclawer zotero CLI subcommand.

Registers 'hfpclawer zotero {search,list,get,tags,check}' for READ operations
against Zotero's local HTTP API via pyzotero.
"""

from __future__ import annotations

import logging
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.table import Table

from hfpclawer.zotero import get_zotero_url, is_zotero_remote

logger = logging.getLogger("zotero.cli")


def _cfg_fallback_get(k: str, d=None):
    """Placeholder cfg.get — replaced by real config inside cmd functions."""
    return d
console = Console()


def _cli_api_url(path: str) -> str:
    """Build absolute Zotero API URL for CLI direct requests."""
    return f"{get_zotero_url()}/api/users/0{path}"


def _cli_api_request(
    url: str,
    method: str = "GET",
    body: bytes | None = None,
    timeout: float = 15.0,
) -> tuple[int, str]:
    """Send a direct HTTP request to Zotero, returning (status_code, body).

    Auto-injects Host spoofing when connecting to a remote Zotero.
    """
    headers: dict[str, str] = {
        "User-Agent": "pyzotero/1.13.2",
        "Zotero-API-Version": "3",
    }
    if is_zotero_remote():
        headers["Host"] = "localhost:23119"
    if body is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8") if e.fp else ""
    except urllib.error.URLError as e:
        return 0, str(e.reason)


def _get_client(**kwargs):
    """Lazy import and create ZoteroClient."""
    from hfpclawer.zotero import ZoteroClient, ZoteroConnectionError

    try:
        return ZoteroClient(**kwargs)
    except ZoteroConnectionError as e:
        console.print(f"[red]❌ {e}[/red]")
        raise SystemExit(1) from e
    except ImportError as e:
        console.print(f"[red]❌ {e}[/red]")
        raise SystemExit(1) from e


def cmd_check(**kwargs) -> None:
    """Check Zotero local API connectivity."""
    zc = _get_client()
    if zc.check_connection():
        console.print("[green]✅ Zotero local API connected[/green]")
        # Quick stats
        try:
            tags = zc.tags()
            zc.top(limit=1)  # connectivity probe
            console.print(f"  Tags:  {len(tags)}")
            console.print("  Items: accessible (no total-count from local API)")
        except Exception:
            pass
    else:
        console.print("[red]❌ Cannot reach Zotero local API[/red]")
        console.print("  Make sure Zotero is running and 'Allow other applications' is enabled.")


def cmd_sync_back(tag: str = "Favor", limit: int = 300, dry_run: bool = False,
                  revoke: bool = False) -> None:
    """Zotero Favor tag → paper_store interest signal (Layer 2 sync-back).

    Only DOI/arXiv-bearing scholarly items are considered (contract filter);
    matching local papers get favorited=1 — the interest signal the learned
    ranker consumes. Zotero is optional: Layer 1 never depends on this.

    --revoke: also revert favorites whose Favor tag vanished from Zotero
    (opt-in — the local API reports no total count, so revocation must be
    explicitly requested after a full pull; never automatic).
    """
    from hfpapers.paper_store import get_store
    from hfpapers.sync_back import sync_back

    zc = _get_client()
    mode = "[dim](dry-run — nothing written)[/dim]" if dry_run else ""
    rev = "[dim](revoke mode — vanished favorites reverted)[/dim]" if revoke else ""
    console.print(f"[cyan]↩ Sync-back Zotero tag '{tag}' → paper_store {mode} {rev}[/cyan]")
    st = sync_back(zc, get_store(), tag=tag, limit=limit, mark=not dry_run, revoke=revoke)

    console.print(f"  total items (tag={tag}):       {st['total']}")
    console.print(f"  scholarly (DOI/arXiv):         {st['scholarly']}  "
                  f"(skipped non-scholarly: {st['skipped_non_scholarly']})")
    console.print(f"  matched in paper_store:        {st['in_store']}  "
                  f"(not in store: {st['skipped_not_in_store']})")
    console.print(f"  newly favorited:               {st['newly_favorited']}")
    if st["revoked_favorites"]:
        console.print(f"  [yellow]revoked (Favor tag gone):    {st['revoked_favorites']}[/yellow]")
    if st["errors"]:
        console.print(f"  parse errors:                  {st['errors']}")
    if st["total"] == 0:
        console.print("[dim]Zotero unreachable or empty tag — Layer 1 unaffected[/dim]")


def cmd_list(
    limit: int = 20,
    tag: str = "",
    item_type: str = "",
    q: str = "",
    start: int = 0,
) -> None:
    """List top-level items from Zotero."""
    zc = _get_client()
    items = zc.top(limit=limit, start=start, q=q, tag=tag, item_type=item_type)

    if not items:
        console.print("[yellow]No items found[/yellow]")
        return

    table = Table(title=f"📚 Zotero Items ({len(items)})")
    table.add_column("Key", style="blue", width=8)
    table.add_column("Type", style="cyan", width=14)
    table.add_column("Title", style="white")
    table.add_column("Tags", style="dim", width=20)
    table.add_column("Date", style="green", width=10)

    for item in items:
        data = item.get("data", {})
        key = data.get("key", item.get("key", "?"))[:8]
        itype = data.get("itemType", "?")[:14]
        title = data.get("title", "(no title)")[:60]
        tags_list = data.get("tags", [])
        tag_str = ", ".join(t["tag"] for t in tags_list[:3]) if tags_list else ""
        date = data.get("date", "")[:10]
        table.add_row(key, itype, title, tag_str, date)

    console.print(table)

    if start + limit < 100:
        console.print(f"  Page {start // limit + 1} | "
                       f"Next: hfpclawer zotero list --start {start + limit} --limit {limit}")


def cmd_search(
    q: str,
    limit: int = 20,
    tag: str = "",
    item_type: str = "",
) -> None:
    """Search items in Zotero by query string."""
    zc = _get_client()
    items = zc.items(limit=limit, q=q, tag=tag, item_type=item_type)

    if not items:
        console.print(f"[yellow]No items match '{q}'[/yellow]")
        return

    table = Table(title=f"🔍 Search: '{q}' ({len(items)} results)")
    table.add_column("Key", style="blue", width=8)
    table.add_column("Type", style="cyan", width=14)
    table.add_column("Title", style="white")
    table.add_column("DOI/URL", style="dim", width=30)

    for item in items:
        data = item.get("data", {})
        key = data.get("key", "?")[:8]
        itype = data.get("itemType", "?")[:14]
        title = data.get("title", "(no title)")[:55]
        doi = data.get("DOI", "") or data.get("url", "") or ""
        doi_short = doi[:30]
        table.add_row(key, itype, title, doi_short)

    console.print(table)


def cmd_get(key: str) -> None:
    """Get details for a single Zotero item by key."""
    zc = _get_client()
    item = zc.get_item(key)

    if not item:
        console.print(f"[red]❌ Item '{key}' not found[/red]")
        return

    data = item.get("data", {})

    console.print(f"[bold]📄 Item: {data.get('title', '(no title)')}[/bold]")
    console.print(f"  Key:      {key}")
    console.print(f"  Type:     {data.get('itemType', '?')}")
    console.print(f"  Date:     {data.get('date', '?')}")
    console.print(f"  DOI:      {data.get('DOI', '—')}")
    console.print(f"  URL:      {data.get('url', '—')}")
    console.print(f"  Publisher: {data.get('publicationTitle', data.get('publisher', '—'))}")
    console.print(f"  Tags:     {', '.join(t['tag'] for t in data.get('tags', []))}")
    console.print(f"  Version:  {data.get('version', '?')}")

    # Creators
    creators = data.get("creators", [])
    if creators:
        console.print(f"  Authors:  {', '.join(c.get('lastName','?') for c in creators[:5])}")
        if len(creators) > 5:
            console.print(f"            ... and {len(creators) - 5} more")

    # Abstract
    abstract = data.get("abstractNote", "")
    if abstract:
        console.print(f"  Abstract: {abstract[:200]}...")

    # Children (attachments, notes)
    children = zc.get_children(key)
    attachments = [c for c in children if c.get("data", {}).get("itemType") == "attachment"]
    notes = [c for c in children if c.get("data", {}).get("itemType") == "note"]

    if attachments:
        console.print(f"\n  [cyan]📎 Attachments ({len(attachments)}):[/cyan]")
        for att in attachments:
            ad = att.get("data", {})
            title = ad.get("title", "untitled")
            content_type = ad.get("contentType", "?")
            path = ad.get("path", ad.get("filename", ""))
            console.print(f"    - {title} ({content_type})")
            if path:
                console.print(f"      path: {path}")

    if notes:
        console.print(f"\n  [yellow]📝 Notes ({len(notes)}):[/yellow]")


def cmd_tags(collection: str = "") -> None:
    """List all tags in the Zotero library."""
    zc = _get_client()
    tags = zc.tags(collection_key=collection)

    if not tags:
        console.print("[yellow]No tags found[/yellow]")
        return

    # Local API returns strings; remote API returns dicts
    if isinstance(tags[0], str):
        # Local mode: plain tag name strings
        table = Table(title=f"🏷️  Tags ({len(tags)})")
        table.add_column("Tag", style="cyan")
        for t in sorted(tags):
            table.add_row(t)
        console.print(table)
        return

    table = Table(title=f"🏷️  Tags ({len(tags)})")
    table.add_column("Tag", style="cyan")
    table.add_column("Items", style="yellow", justify="right")

    for t in sorted(tags, key=lambda x: -x.get("meta", {}).get("numItems", 0)):
        tag_name = t.get("tag", "?")
        count = t.get("meta", {}).get("numItems", "?")
        table.add_row(tag_name, str(count))

    console.print(table)


def cmd_tag_report(
    limit: int = 200,
    chart_path: str = "",
    wordcloud: bool = False,
) -> None:
    """Scan Zotero library and produce tag optimization report.

    Uses spaCy to extract candidate tags from all item titles, then
    computes TF-IDF to find high-value terms NOT yet used as tags.

    Args:
        limit: Max items to scan (default 200).
        chart_path: Optional path to save bar chart.
        wordcloud: If True, generate word cloud instead of bar chart.
    """
    from hfpapers.nlp import configure as configure_nlp

    # Configure spaCy (lazy — no-op if already loaded)
    configure_nlp("en_core_web_md")

    zc = _get_client()
    console.print(f"[dim]Scanning up to {limit} Zotero items with spaCy...[/dim]")

    from hfpapers.nlp.tag_analysis import (
        analyze_library_tags,
        plot_simple_wordcloud,
        report_chart,
        report_text,
    )

    analysis = analyze_library_tags(zc, limit=limit, top_n=30)

    # Print report
    report = report_text(analysis)
    console.print(report)

    # Generate chart if requested
    if chart_path:
        if wordcloud:
            saved = plot_simple_wordcloud(analysis, output_path=chart_path)
        else:
            saved = report_chart(analysis, output_path=chart_path)
        if saved:
            console.print(f"\n[green]📊 Chart saved:[/green] {saved}")
        else:
            console.print("\n[yellow]⚠️  Chart generation skipped (matplotlib not available)[/yellow]")

    # Summary
    gaps = analysis["tag_gaps"]
    if gaps:
        console.print(f"\n[bold cyan]💡 Top suggestion:[/bold cyan] add tag [bold]'{gaps[0]['term']}'[/bold] "
                      f"(appears in {gaps[0]['df']} papers, TF-IDF={gaps[0]['tfidf']})")


def cmd_innovate(
    arxiv_id: str = "",
    zotero_key: str = "",
    dry_run: bool = False,
    push: bool = False,
) -> None:
    """Extract innovation keywords from a paper and write to Zotero extra.

    Uses spaCy to extract 5-7 structured innovation points (method, field,
    technique, dataset, metric, application, core concept) from the paper's
    title and abstract.

    Args:
        arxiv_id: arXiv ID to look up (from paper_store or Zotero).
        zotero_key: Direct Zotero item key (skips arXiv ID lookup).
        dry_run: Show extracted keywords without writing.
        push: Write innovation keywords to Zotero extra field.

    Examples:
        hfpclawer zotero innovate 2501.01934               # Preview
        hfpclawer zotero innovate 2501.01934 --push         # Extract + write
        hfpclawer zotero innovate --key ABC123 --push       # By Zotero key
    """
    from hfpapers.nlp import configure as configure_nlp
    from hfpapers.nlp.innovation import (
        extract_innovation_points,
        format_innovation_summary,
    )
    from hfpapers.nlp.tags import generate_tags

    # Load spaCy
    configure_nlp("en_core_web_md")

    zc = _get_client()
    abstract = ""
    title = ""
    key = zotero_key or ""

    # ── Resolve paper metadata ──
    if not key and arxiv_id:
        # Try Zotero lookup first
        matches = zc.search_by_arxiv_id(arxiv_id)
        if matches:
            data = matches[0].get("data", {})
            key = data.get("key", "")
            title = data.get("title", "")
            abstract = data.get("abstractNote", "")
            console.print(f"[dim]Found in Zotero: {title[:60]}...[/dim]")
        else:
            # Fallback: paper_store
            try:
                from hfpapers.paper_store import get_store
                store = get_store()
                rec = store.get_paper_by_identifier("arxiv", arxiv_id)
                if rec:
                    title = rec.title or ""
                    abstract = rec.abstract or ""
                    console.print(f"[dim]Found in paper_store: {title[:60]}...[/dim]")
            except Exception:
                pass

    elif key:
        # Direct Zotero key
        item = zc.get_item(key)
        if item:
            data = item.get("data", {})
            title = data.get("title", "")
            abstract = data.get("abstractNote", "")
            arxiv_id = arxiv_id or data.get("key", "")

    if not title:
        console.print("[yellow]⚠️  No title found. Provide --aid, arXiv ID, or --key.[/yellow]")
        return

    # ── Extract innovation points ──
    points = extract_innovation_points(abstract, title)
    auto_tags = generate_tags(title, abstract)

    console.print(f"\n[bold]📄 {title[:70]}...[/bold]")
    console.print(f"[dim]arXiv: {arxiv_id}  |  Zotero key: {key}[/dim]")
    console.print("")

    # Show innovation points
    console.print("[bold cyan]🎯 Innovation Keywords:[/bold cyan]")
    summary = format_innovation_summary(points)
    console.print(summary)

    # Show auto-tags
    console.print("\n[bold cyan]🏷️ Auto-Tags:[/bold cyan]")
    console.print(f"  {' • '.join(auto_tags[:10])}")

    # Flatten innovation points for extra field
    extra_fields = {}
    for slot, values in points.items():
        if values:
            extra_fields[f"innovation_{slot}"] = "; ".join(values[:2])
    if auto_tags:
        extra_fields["innovation_tags"] = "; ".join(auto_tags[:8])

    # ── Write to Zotero extra ──
    if push and key:
        console.print("\n[dim]Writing to Zotero extra field...[/dim]")
        ok = zc.update_item_extra(key, extra_fields)
        if ok:
            console.print(f"[green]✅ Innovation keywords written to extra field for {key}[/green]")
        else:
            console.print(f"[red]❌ Failed to write to Zotero for {key}[/red]")
    elif push and not key:
        console.print("[yellow]⚠️  No Zotero key found. Use --key to specify.[/yellow]")
    elif dry_run or not push:
        console.print("\n[dim]--- Preview only. Add --push to write to Zotero extra. ---[/dim]")
        for label, value in extra_fields.items():
            console.print(f"  [cyan]{label}:[/cyan] {value}")


def cmd_children(key: str) -> None:
    """List children (attachments, notes) for a Zotero item."""
    zc = _get_client()
    children = zc.get_children(key)

    if not children:
        console.print(f"[yellow]No children for {key}[/yellow]")
        return

    table = Table(title=f"📎 Children of {key} ({len(children)})")
    table.add_column("Key", style="blue", width=8)
    table.add_column("Type", style="cyan", width=14)
    table.add_column("Title", style="white")
    table.add_column("Content Type", style="dim", width=20)

    for child in children:
        data = child.get("data", {})
        ckey = data.get("key", "?")[:8]
        ctype = data.get("itemType", "?")[:14]
        title = data.get("title", "(no title)")[:50]
        content_type = data.get("contentType", data.get("note", "")[:20])
        table.add_row(ckey, ctype, title, content_type)

    console.print(table)


def cmd_push(
    arxiv_id: str = "",
    aid: str = "",
    doi: str = "",
    title: str = "",
    url: str = "",
    venue: str = "",
    abstract: str = "",
    source: str = "cli",
    tag: str = "",
    dry_run: bool = False,
    dedup: bool = True,
    with_pdf: bool = False,
) -> None:
    """Push a paper to Zotero via Connector protocol (POST /connector/saveItems).

    Args:
        arxiv_id: arXiv ID to look up from paper_store.
        aid: Alias for arxiv_id.
        doi: DOI (direct push without paper_store).
        title: Paper title (required if not from paper_store).
        url: Source URL.
        venue: Journal/conference name.
        abstract: Paper abstract.
        source: Source tag (e.g., 'cron:coc', 'cli').
        tag: Additional Zotero tags (comma-separated).
        dry_run: Print what would be sent without actually POSTing.
        dedup: Skip if paper already exists in Zotero (default: True).
        with_pdf: Also attach the local PDF file (searched in paper_store's pdf_dir).
    """
    from hfpclawer.zotero.connector import (
        ConnectorError,
        ZoteroConnector,
        paper_to_zotero_item,
    )

    paper = {}

    # Resolve from paper_store if arxiv_id provided
    resolved_id = arxiv_id or aid
    if resolved_id:
        # Try paper_store lookup
        conn = ZoteroConnector()
        paper = conn._lookup_paper_store(resolved_id)
        if not paper:
            console.print(f"[yellow]Paper '{resolved_id}' not in paper_store. "
                          "Provide --title and other fields for direct push.[/yellow]")
            # Still allow direct push
            paper = {"arxiv_id": resolved_id}

    # Fill in/override fields from CLI args
    if title:
        paper["title"] = title
    if doi:
        paper["doi"] = doi
    if url:
        paper["url"] = url
    if venue:
        paper["venue"] = venue
    if abstract:
        paper["abstract"] = abstract
    if source:
        paper["source"] = source
    if resolved_id:
        paper["arxiv_id"] = resolved_id

    # Validate
    if not paper.get("title"):
        console.print("[red]❌ Title is required. Provide --title or push from paper_store with --aid.[/red]")
        return

    # Build Zotero item
    item = paper_to_zotero_item(paper)

    # Add extra tags from CLI
    if tag:
        for t in tag.split(","):
            t = t.strip()
            if t:
                item["tags"].append({"tag": t, "type": 1})

    if dry_run:
        console.print("[bold]📋 Dry Run — would send to Zotero:[/bold]")
        console.print(f"  Title:    {item['title'][:80]}")
        console.print(f"  Type:     {item['itemType']}")
        console.print(f"  DOI:      {item.get('DOI', '—')}")
        console.print(f"  URL:      {item.get('url', '—')}")
        console.print(f"  Tags:     {', '.join(t['tag'] for t in item.get('tags', []))}")
        console.print(f"  Extra:    {item.get('extra', '—')}")
        console.print(f"  Venue:    {item.get('publicationTitle', '—')}")
        _print_creators_preview(item)
        console.print("\n[yellow]Dry run mode — no data sent to Zotero[/yellow]")
        return

    # Dedup check — skip if paper already exists in Zotero
    dedup_key = resolved_id or doi or ""
    if dedup and dedup_key:
        try:
            from hfpclawer.zotero import ZoteroClient
            zc = ZoteroClient()
            if dedup_key.startswith("2") and "." in dedup_key:
                # Looks like an arXiv ID
                existing = zc.is_arxiv_in_zotero(dedup_key)
            elif dedup_key.startswith("10."):
                # Looks like a DOI
                existing = zc.search_by_doi(dedup_key)
                existing = existing.get("data", {}).get("key") if existing else None
            else:
                existing = zc.is_arxiv_in_zotero(dedup_key)

            if existing:
                console.print(f"[yellow]⏭️ Already in Zotero (key={existing})[/yellow]")
                console.print(f"  Check: hfpclawer zotero get {existing}")
                return
        except Exception:
            pass  # Dedup failure is non-blocking — proceed anyway

    # POST to Zotero
    uri = paper.get("url", "") or f"https://arxiv.org/abs/{resolved_id or ''}"
    console.print("[dim]Sending to Zotero via /connector/saveItems...[/dim]")

    try:
        conn = ZoteroConnector()
        result = conn.save_items([item], uri=uri)

        if result.get("status") == 201:
            console.print("[green]✅ Pushed to Zotero![/green]")
            console.print(f"  Session:  {result['session_id'][:24]}...")
            console.print(f"  Title:    {item['title'][:60]}")
            console.print(f"  Tags:     {', '.join(t['tag'] for t in item['tags'])}")

            # ── PDF attachment ──────────────────────────────
            if with_pdf:
                _push_after_attach(
                    conn, item, paper, result, resolved_id, console,
                )
            else:
                console.print(f"\n[dim]Check with: hfpclawer zotero search \"{item['title'][:30]}\"[/dim]")
        else:
            console.print(f"[red]❌ Push failed (HTTP {result.get('status')})[/red]")
            if result.get("error"):
                console.print(f"  Error: {result['error']}")
            if result.get("response_text"):
                console.print(f"  Response: {result['response_text'][:200]}")
    except ConnectorError as e:
        console.print(f"[red]❌ {e}[/red]")
    except Exception as e:
        console.print(f"[red]❌ Unexpected error: {e}[/red]")


def cmd_push_batch(
    source_filter: str = "cron:",
    limit: int = 10,
    dry_run: bool = False,
    dedup: bool = True,
) -> None:
    """Batch push un-pushed papers from paper_store to Zotero.

    Scans paper_store for papers whose source matches the filter
    and have not been pushed yet (no Zotero record recorded).

    Args:
        source_filter: Only push papers with this source prefix (default: "cron:")
        limit: Max papers to push in one batch (default: 10).
        dry_run: Just show what would be pushed.
        dedup: Skip papers already in Zotero (default: True).
    """
    from hfpclawer.zotero.connector import ConnectorError, ZoteroConnector
    try:
        from hfpapers.paper_store import get_store
        store = get_store()
    except Exception as e:
        console.print(f"[red]❌ Cannot access paper_store: {e}[/red]")
        return

    # Get candidates from paper_store (exclude already-pushed)
    with store._conn() as conn:
        rows = conn.execute(
            """SELECT p.sf_id, p.title, p.source FROM papers p
               WHERE p.source LIKE ?1
               AND p.zotero_pushed_at = ''
               ORDER BY p.created_at DESC LIMIT ?2""",
            (f"{source_filter}%", limit),
        ).fetchall()

    if not rows:
        console.print(f"[yellow]No papers match source filter '{source_filter}'[/yellow]")
        return

    # Filter: skip papers already in Zotero (dedup by arXiv ID in extra field)
    from hfpclawer.zotero import ZoteroClient
    zc = ZoteroClient()
    pushed = 0
    skipped = 0
    errors = 0
    dedup_skipped = 0

    console.print(f"[bold]Batch push: {len(rows)} candidates[/bold]")

    for row in rows:
        sf_id = row["sf_id"]
        title = (row["title"] or "")[:60]
        source = row["source"] or "unknown"

        # Get arxiv_id
        ids = store.get_identifiers(sf_id)
        arxiv_id = next(
            (i.id_value for i in ids if i.id_type == "arxiv"), None
        )
        if not arxiv_id:
            logger.debug("Skipping sf_id=%s: no arxiv_id", sf_id)
            skipped += 1
            continue

        # Dedup check — skip if already in Zotero
        if dedup:
            try:
                existing_key = zc.is_arxiv_in_zotero(arxiv_id)
                if existing_key:
                    dedup_skipped += 1
                    if dry_run:
                        console.print(f"  [dim]⏭️ [{arxiv_id}] {title} (already in Zotero)[/dim]")
                    continue
            except Exception:
                pass  # Dedup failure is non-blocking

        if dry_run:
            console.print(f"  📄 [{source}] {arxiv_id} {title}")
            continue

        # Push
        paper = {
            "sf_id": sf_id,
            "arxiv_id": arxiv_id,
            "title": row["title"],
            "source": source,
        }
        # Enrich with ID data
        doi = next((i.id_value for i in ids if i.id_type == "doi"), "")
        if doi:
            paper["doi"] = doi

        item = _paper_to_zotero_item_simple(paper)
        uri = f"https://arxiv.org/abs/{arxiv_id}"

        try:
            conn = ZoteroConnector()
            result = conn.save_items([item], uri=uri)
            if result.get("status") == 201:
                pushed += 1
                console.print(f"  [green]✅[/green] [{arxiv_id}] {title}")
                # Write-back verification & mark pushed
                _mark_pushed_after_save(store, sf_id, arxiv_id, doi, console)
            else:
                errors += 1
                console.print(f"  [red]❌[/red] [{arxiv_id}] {result.get('error', '?')}")
        except ConnectorError:
            errors += 1
            console.print(f"  [red]❌[/red] [{arxiv_id}] Connector unreachable")

    if dry_run:
        console.print(f"\n[yellow]Dry run: {len(rows)} candidates"
                       f" ({dedup_skipped} dedup-skipped)[/yellow]")
        console.print("  Use without --dry-run to actually push.")
    else:
        console.print(f"\n[bold]Batch complete: {pushed} pushed, "
                       f"{dedup_skipped} dedup-skipped, "
                       f"{skipped} skipped, {errors} errors[/bold]")


def cmd_annotate(
    arxiv_id: str = "",
    zotero_key: str = "",
    fmt: str = "markdown",
    output: str = "",
    color_hex: str = "",
    color_name: str = "",
) -> None:
    """Extract PDF annotations (highlights/underlines) from a Zotero paper.

    Reads the PDF via its local file path (from Zotero API), parses
    annotations with PyMuPDF, and renders as Markdown or JSON.

    Args:
        arxiv_id: arXiv ID to look up (e.g., "1905.01522").
        zotero_key: Direct Zotero item key (e.g., "XVLZEDC4").
        fmt: Output format: "markdown" (default) or "json".
        output: Write to file instead of stdout.
        color_hex: Only show annotations with this hex color (e.g., "#ffd400").
        color_name: Only show annotations with this color name (case-insensitive).
    """
    from hfpclawer.zotero.annotations import (
        color_filter,
        format_json,
        format_markdown,
        get_pdf_annotations,
    )

    if not arxiv_id and not zotero_key:
        console.print("[yellow]Provide --aid or --key[/yellow]")
        return

    with console.status("[dim]Resolving paper and extracting annotations...[/dim]"):
        result = get_pdf_annotations(arxiv_id=arxiv_id, zotero_key=zotero_key)

    if "error" in result:
        console.print(f"[red]❌ {result['error']}[/red]")
        return

    anns = result["annotations"]
    title = result.get("title", "")
    parent_key = result.get("parent_key", "")

    # Apply color filter
    if color_hex or color_name:
        anns = color_filter(anns, color_hex=color_hex, color_name=color_name)

    if fmt == "json":
        content = format_json(anns)
    else:
        content = format_markdown(anns, title=title, parent_key=parent_key)

    if not anns:
        console.print(f"[yellow]📄 {title}[/yellow]")
        console.print("[yellow]No annotations found in the PDF.[/yellow]")
        console.print("  Open the PDF in Zotero and add highlights first.")
        if output:
            Path(output).write_text(content, encoding="utf-8")
            console.print(f"  [dim]Wrote to: {output}[/dim]")
        return

    if output:
        Path(output).write_text(content, encoding="utf-8")
        console.print(f"[green]✅ {len(anns)} annotation(s) saved to {output}[/green]")
    else:
        console.print(content)


# ── Supported export formats ─────────────────────
EXPORT_FORMATS = {
    "bibtex": "BibTeX (.bib)",
    "biblatex": "BibLaTeX (.bib)",
    "ris": "RIS (.ris)",
    "csljson": "CSL JSON (.json)",
    "csv": "CSV (.csv)",
    "mods": "MODS XML (.xml)",
    "tei": "TEI XML (.xml)",
    "rdf_zotero": "Zotero RDF (.rdf)",
    "rdf_dc": "Dublin Core RDF (.rdf)",
    "rdf_bibliontology": "Bibliontology RDF (.rdf)",
    "coins": "COinS",
    "refer": "Refer",
    "bookmarks": "Bookmarks",
    "wikipedia": "Wikipedia Citation",
}


def cmd_export(
    arxiv_id: str = "",
    zotero_key: str = "",
    collection_key: str = "",
    export_all: bool = False,
    fmt: str = "biblatex",
    output: str = "",
) -> None:
    """Export references from Zotero in bibliographic format.

    Uses Zotero's native export translators via the local API
    (GET /items?format=...). No Better BibTeX plugin required.

    Args:
        arxiv_id: arXiv ID to export a single paper.
        zotero_key: Zotero item key to export.
        collection_key: Export all items in a collection.
        export_all: Export the entire Zotero library.
        fmt: Export format (default: biblatex). See --list-formats.
        output: Write to file instead of stdout.

    Formats:
        bibtex, biblatex, ris, csljson, csv, mods, tei,
        rdf_zotero, rdf_dc, rdf_bibliontology, coins, refer,
        bookmarks, wikipedia
    """

    # Validate format
    if fmt not in EXPORT_FORMATS and fmt != "list-formats":
        console.print(f"[red]❌ Unknown format: '{fmt}'[/red]")
        console.print(f"  Available: {', '.join(EXPORT_FORMATS.keys())}")
        return

    if fmt == "list-formats":
        console.print("[bold]Available export formats:[/bold]")
        for name, desc in sorted(EXPORT_FORMATS.items()):
            console.print(f"  {name:20s} {desc}")
        return

    # Build API URL
    if arxiv_id:
        # Resolve to Zotero key
        from hfpclawer.zotero import ZoteroClient
        zc = ZoteroClient()
        parent_key = zc.is_arxiv_in_zotero(arxiv_id)
        if not parent_key:
            console.print(f"[red]❌ arXiv {arxiv_id} not found in Zotero[/red]")
            return
        api_path = f"/items/{parent_key}?format={fmt}"

    elif zotero_key:
        # Verify key exists
        api_path = f"/items/{zotero_key}?format={fmt}"
        test_url = _cli_api_url(f"/items/{zotero_key}")
        status, body = _cli_api_request(test_url, timeout=10)
        if status == 404:
            console.print(f"[red]❌ Zotero key '{zotero_key}' not found[/red]")
            return
        elif status >= 400 or status == 0:
            console.print(f"[red]❌ Zotero API error: HTTP {status}[/red]")
            return

    elif collection_key:
        api_path = f"/collections/{collection_key}/items?format={fmt}"

    elif export_all:
        api_path = f"/items?format={fmt}&limit=5000"

    else:
        console.print(
            "[yellow]Specify a paper (--aid, --key), "
            "--collection, or --all[/yellow]"
        )
        return

    # Fetch
    url = _cli_api_url(api_path)
    console.print(f"[dim]Fetching: {url[:80]}...[/dim]")

    status, body = _cli_api_request(url, timeout=30)
    if status >= 400 or status == 0:
        console.print(f"[red]❌ Zotero API returned HTTP {status}[/red]")
        return

    content = body

    if not content.strip():
        console.print("[yellow]No results to export.[/yellow]")
        return

    # Output
    if output:
        Path(output).write_text(content, encoding="utf-8")
        console.print(f"[green]✅ Exported to {output} ({len(content)} bytes)[/green]")
    else:
        # Display with rich syntax highlighting for known formats
        if fmt in ("bibtex", "biblatex"):
            from rich.syntax import Syntax
            syntax = Syntax(content, "bibtex", theme="ansi_dark")
            console.print(syntax)
        elif fmt == "csljson":
            import json as _json
            try:
                parsed = _json.loads(content)
                console.print_json(data=parsed if isinstance(parsed, dict) else parsed[0] if parsed else {})
            except Exception:
                console.print(content)
        elif fmt == "ris":
            from rich.syntax import Syntax
            syntax = Syntax(content[:2000], "text", theme="ansi_dark")
            console.print(syntax)
        else:
            console.print(content[:2000])
        console.print(f"\n[dim]{len(content)} bytes | format: {fmt}[/dim]")
        console.print("  [dim]Use --output <file> to save.[/dim]")


def cmd_note(
    arxiv_id: str = "",
    zotero_key: str = "",
    output: str = "",
    raw: bool = False,
) -> None:
    """Read notes attached to a Zotero paper.

    Notes are child items with itemType='note'. The note content
    is stored as HTML by Zotero's rich text editor.

    Args:
        arxiv_id: arXiv ID to look up.
        zotero_key: Direct Zotero item key.
        output: Write to file instead of stdout.
        raw: Show raw HTML instead of rendered text.
    """
    import json

    # Resolve to parent key
    parent_key = ""
    title = ""

    if arxiv_id:
        from hfpclawer.zotero import ZoteroClient
        zc = ZoteroClient()
        parent_key = zc.is_arxiv_in_zotero(arxiv_id)
        if not parent_key:
            console.print(f"[red]❌ arXiv {arxiv_id} not found in Zotero[/red]")
            return
    elif zotero_key:
        parent_key = zotero_key
        try:
            item = _api_get_single(parent_key)
            if "error" in item:
                console.print(f"[red]❌ {item['error']}[/red]")
                return
            title = item.get("title", "")
        except Exception as e:
            console.print(f"[red]❌ Zotero error: {e}[/red]")
            return
    else:
        console.print("[yellow]Provide --aid or --key[/yellow]")
        return

    # Get item title if not already fetched
    if not title:
        try:
            item = _api_get_single(parent_key)
            title = item.get("title", "")
        except Exception:
            title = ""

    # Fetch children
    try:
        url = _cli_api_url(f"/items/{parent_key}/children")
        status, body = _cli_api_request(url, timeout=15)
        if status >= 400 or status == 0:
            console.print(f"[red]❌ Cannot fetch notes: HTTP {status}[/red]")
            return
        children = json.loads(body)
    except Exception as e:
        console.print(f"[red]❌ Cannot fetch notes: {e}[/red]")
        return

    # Filter notes
    notes = [c for c in children if c.get("data", {}).get("itemType") == "note"]

    if not notes:
        console.print(f"[yellow]📄 {title or parent_key}[/yellow]")
        console.print("[yellow]No notes attached to this paper.[/yellow]")
        return

    # Build output
    lines: list[str] = []
    if title:
        lines.append(f"📋 Notes for: {title}")
    else:
        lines.append(f"📋 Notes for: {parent_key}")
    lines.append("")

    for i, note in enumerate(notes, 1):
        nd = note.get("data", {})
        nkey = nd.get("key", "?")
        html_content = nd.get("note", "")

        lines.append(f"─── Note {i} [{nkey}] ───")

        if raw:
            lines.append(html_content)
        else:
            # Strip HTML tags for readable display
            try:
                from bs4 import BeautifulSoup
                soup = BeautifulSoup(html_content, "html.parser")
                text = soup.get_text(separator="\n", strip=True)
                lines.append(text)
            except ImportError:
                # Fallback: basic tag stripping
                import re
                text = re.sub(r"<[^>]+>", "", html_content)
                text = re.sub(r"\n{3,}", "\n\n", text)
                lines.append(text.strip())

        lines.append("")

    content = "\n".join(lines)

    if output:
        Path(output).write_text(content, encoding="utf-8")
        console.print(f"[green]✅ {len(notes)} note(s) saved to {output}[/green]")
    else:
        console.print(content)


def _api_get_single(key: str) -> dict:
    """Fetch a single Zotero item by key, return its data dict."""
    import json

    url = _cli_api_url(f"/items/{key}")
    status, body = _cli_api_request(url, timeout=10)
    if status == 404:
        return {"error": f"Zotero key '{key}' not found"}
    elif status >= 400 or status == 0:
        return {"error": f"Zotero API error: HTTP {status}"}
    item = json.loads(body)
    data = item.get("data", {}) or {}
    if not data:
        return {"error": f"Item '{key}' not found"}
    return dict(data)


def _print_creators_preview(item: dict) -> None:
    """Print creator info for dry-run display."""
    creators = item.get("creators", [])
    if creators:
        names = [f"{c.get('lastName','?')}, {c.get('firstName','?')}" for c in creators[:3]]
        console.print(f"  Authors:  {'; '.join(names)}")
        if len(creators) > 3:
            console.print(f"            ... and {len(creators)-3} more")


def _push_after_attach(
    conn,
    item,
    paper,
    save_result,
    resolved_id: str,
    console: Console,
) -> None:
    """After metadata push, attach PDF via saveAttachment."""
    import os

    from hfpclawer.zotero.connector import ConnectorError

    session_id = save_result["session_id"]

    # Step 1: get recognized item key
    try:
        rec = conn.get_recognized_item(session_id)
    except ConnectorError as e:
        console.print(f"  [yellow]⚠️  Cannot check recognized item: {e}[/yellow]")
        return

    parent_key = None
    if rec and isinstance(rec, dict):
        parent_key = rec.get("itemID") or rec.get("key") or rec.get("data", {}).get("key", "")
    if not parent_key:
        # Fallback: poll once more after a short wait
        import time
        time.sleep(2)
        try:
            rec = conn.get_recognized_item(session_id)
            if rec and isinstance(rec, dict):
                parent_key = rec.get("itemID") or rec.get("key") or rec.get("data", {}).get("key", "")
        except ConnectorError:
            pass

    if not parent_key:
        console.print("  [yellow]⚠️  Could not get Zotero item key for PDF attachment[/yellow]")
        console.print("  [dim]The metadata was saved; PDF can be attached manually from local storage.[/dim]")
        return

    # Step 1.5: audit check — only attach PDF for content-verified papers (audit_level >= 2)
    arxiv_id = paper.get("arxiv_id") or resolved_id or ""
    is_verified = False
    try:
        from hfpapers.paper_store import get_store
        store = get_store()
        rec = store.get_paper_by_identifier("arxiv", arxiv_id)
        if rec:
            # audit_level >= 2 means content verified (PDF downloaded + extractable)
            is_verified = rec.audit_level >= 2
    except Exception:
        pass  # Audit check failure is non-blocking

    if not is_verified:
        console.print(f"  [yellow]⏭️  PDF skipped: {arxiv_id} audit_level < 2 (need content verification)[/yellow]")
        console.print("  [dim]PDF must be downloaded and validated before push. Run 'hfpclawer download' first.[/dim]")
        return

    # Step 2: resolve PDF path
    # Search order: paper_store pdf_dir, resolved_id.pdf in data/pdfs, generic ~/hfpclawer/data/pdfs/
    pdf_candidates = []
    arxiv_id = paper.get("arxiv_id") or resolved_id or ""

    # From paper_store config
    try:
        from hfpapers.config import get as cfg_get
        base = cfg_get("data_dir") or "data"
        pdf_dir = cfg_get("paths.pdf_dir") or f"{base}/pdfs"
        pdf_dir = os.path.expanduser(pdf_dir)
        if not os.path.isabs(pdf_dir):
            # Try relative to repo root
            import hfpclawer
            hf_dir = os.path.dirname(os.path.dirname(hfpclawer.__file__))
            pdf_dir = os.path.join(hf_dir, pdf_dir)
        pdf_candidates.append(os.path.join(pdf_dir, f"{arxiv_id}.pdf"))
    except Exception:
        pass

    # Fallback paths
    pdf_candidates.extend([
        os.path.expanduser(f"~/hfpclawer/data/pdfs/{arxiv_id}.pdf"),
        os.path.expanduser(f"~/Documents/Gitlab/Agentic4Sci/hfpapers-crawler/data/pdfs/{arxiv_id}.pdf"),
    ])

    pdf_path = None
    for cand in pdf_candidates:
        if os.path.isfile(cand):
            pdf_path = cand
            break

    if not pdf_path:
        console.print(f"  [yellow]⚠️  No local PDF found for {arxiv_id}[/yellow]")
        console.print("  [dim]The metadata was saved; PDF will sync via WebDAV.[/dim]")
        return

    # Step 3: attach PDF
    console.print(f"  [dim]Attaching PDF: {os.path.basename(pdf_path)} ({os.path.getsize(pdf_path)//1024} KB)...[/dim]")
    try:
        att_result = conn.save_attachment(
            session_id=session_id,
            parent_item_key=parent_key,
            pdf_path=pdf_path,
            title=f"{item.get('title', 'PDF')[:100]}",
            url=paper.get("url", ""),
        )
        if att_result.get("status", 0) in (200, 201):
            console.print(f"  [green]✅ PDF attached! (key={parent_key})[/green]")
            # Bump audit level to 2 (content verified) + mark zotero pushed
            try:
                from hfpapers.paper_store import get_store
                s = get_store()
                rec = s.get_paper_by_identifier("arxiv", arxiv_id)
                if rec:
                    s.set_audit_level(rec.sf_id, 2)
                    s.mark_zotero_pushed(rec.sf_id)
                    console.print("  [dim]  ✓ audit_level=2, zotero_pushed recorded[/dim]")
            except Exception as e:
                logger.debug("audit_level promotion failed: %s", e)
        else:
            console.print(f"  [yellow]⚠️  PDF attach: HTTP {att_result.get('status')} "
                          f"{att_result.get('error', '')}[/yellow]")
    except FileNotFoundError as e:
        console.print(f"  [red]❌ PDF not found: {e}[/red]")
    except ConnectorError as e:
        console.print(f"  [red]❌ Connector error: {e}[/red]")
    except Exception as e:
        console.print(f"  [red]❌ Unexpected: {e}[/red]")


def _paper_to_zotero_item_simple(paper: dict) -> dict:
    """Minimal paper-to-Zotero conversion for batch push (avoids full connector import)."""
    from hfpclawer.zotero.connector import paper_to_zotero_item
    return paper_to_zotero_item(paper)


def _mark_pushed_after_save(store, sf_id: int, arxiv_id: str, doi: str, console) -> None:
    """Write-back verification + mark zotero_pushed_at after successful save.

    Three-step confirmation:
      1. Wait briefly for Zotero async processing
      2. Poll Zotero local API to verify the item exists
      3. Mark in paper_store
    """
    import time

    # Step 1: wait for Zotero async processing
    time.sleep(2)

    # Step 2: write-back verification — poll Zotero local API
    verified = False
    for attempt in range(3):
        try:
            from hfpclawer.zotero import ZoteroClient
            zc = ZoteroClient()
            if arxiv_id:
                existing = zc.is_arxiv_in_zotero(arxiv_id)
                if existing:
                    verified = True
                    break
            if doi and not verified:
                from hfpclawer.zotero import ZoteroClient
                zc2 = ZoteroClient()
                match = zc2.search_by_doi(doi)
                if match and match.get("data", {}).get("key"):
                    verified = True
                    break
        except Exception:
            pass
        if attempt < 2:
            time.sleep(3)

    if not verified:
        console.print(f"  [yellow]⚠️  Write-back: {arxiv_id} not confirmed in Zotero (async delay?)[/yellow]")
        console.print("  [dim]Will retry on next push-batch run.[/dim]")
        return

    # Step 3: mark pushed in paper_store (idempotency guard)
    try:
        store.mark_zotero_pushed(sf_id)
        console.print("  [dim]  ✓ zotero_pushed_at recorded[/dim]")
    except Exception as e:
        logger.warning("Failed to mark zotero_pushed for sf_id=%s: %s", sf_id, e)


# ════════════════════════════════════════════════════════════
# cmd_ingest — Zotero 本地 PDF → hfpclawer paper_store → wiki/raw
# ════════════════════════════════════════════════════════════

def cmd_ingest(
    arxiv_id: str,
    output: str = "",
    no_wiki: bool = False,
    verbose: bool = False,
) -> None:
    """Ingest a paper from Zotero's local PDF into paper_store + wiki/raw.

    Pipeline:
      1. Resolve arXiv ID → Zotero item → local PDF path
      2. Copy PDF to hfpclawer's pdfs/ directory
      3. Convert PDF → Markdown (pymupdf4llm)
      4. Ingest metadata into paper_store (sqllite)
      5. Write wiki/raw/papers/{arxiv_id}.md with frontmatter + annotations

    Args:
        arxiv_id: arXiv ID to ingest
        output: Override output path for wiki raw file
        no_wiki: Skip wiki/raw output (only paper_store + PDF + MD)
        verbose: Print each step
    """
    import shutil
    import ssl
    import urllib.error
    import urllib.request
    from datetime import datetime, timezone
    from hashlib import sha256

    # ── Step 0: normalize arXiv ID ──
    aid = arxiv_id.strip().rstrip("/").split("abs/")[-1].split("arXiv:")[-1].strip()
    console.print(f"\n[bold]📥 Ingesting {aid}[/bold]\n")

    # ── Step 1: fetch arXiv metadata FIRST (gets title → accelerates Zotero lookup) ──
    console.print("[dim] 1/7 Fetching arXiv metadata...[/dim]")
    arxiv_title = ""
    arxiv_authors = ""
    arxiv_abstract = ""
    arxiv_categories = ""
    try:
        from xml.etree import ElementTree as ET
        url = f"http://export.arxiv.org/api/query?id_list={aid}&max_results=1"
        ctx = ssl._create_unverified_context()
        req = urllib.request.Request(url, headers={"User-Agent": "hfpclawer/0.9"})
        with urllib.request.urlopen(req, timeout=15, context=ctx) as resp:
            raw_xml = resp.read()
        root = ET.fromstring(raw_xml)
        ns = {"a": "http://www.w3.org/2005/Atom"}
        entry = root.find("a:entry", ns)
        if entry is not None:
            title_el = entry.find("a:title", ns)
            if title_el is not None and title_el.text:
                arxiv_title = " ".join(title_el.text.split())
            authors = []
            for au in entry.findall("a:author", ns):
                name_el = au.find("a:name", ns)
                if name_el is not None and name_el.text:
                    authors.append(name_el.text)
            arxiv_authors = ", ".join(authors)
            abs_el = entry.find("a:summary", ns)
            if abs_el is not None and abs_el.text:
                arxiv_abstract = " ".join(abs_el.text.split())
            cats = []
            for cat in entry.findall("a:category", ns):
                term = cat.get("term", "")
                if term:
                    cats.append(term)
            arxiv_categories = ", ".join(cats)
        console.print(f"  ✓ Title: {arxiv_title[:80]}...")
        if arxiv_authors:
            console.print(f"  ✓ Authors: {arxiv_authors[:80]}...")
    except Exception as e:
        if verbose:
            console.print(f"  [yellow]⚠️  arXiv meta: {e}[/yellow]")

    # ── Step 2: resolve PDF path from Zotero (uses title for fast keyword search) ──
    console.print("[dim] 2/7 Resolving PDF in Zotero...[/dim]")
    from hfpclawer.zotero.annotations import resolve_pdf_path

    info = resolve_pdf_path(arxiv_id=aid, title=arxiv_title)
    if "error" in info:
        console.print(f"[red]❌ {info['error']}[/red]")
        return

    zotero_pdf = info["pdf_path"]
    parent_key = info.get("parent_key", "")
    console.print(f"  ✓ Source: {zotero_pdf}")
    if arxiv_title:
        console.print(f"  ✓ Title: {arxiv_title[:80]}...")
    console.print(f"  ✓ Zotero key: {parent_key}")

    pdf_size = Path(zotero_pdf).stat().st_size
    console.print(f"  ✓ PDF size: {pdf_size // 1024} KB")

    # ── Step 3: copy PDF to hfpclawer's data dir ──
    console.print("[dim] 3/7 Copying PDF to hfpclawer storage...[/dim]")
    pdf_dir: Path
    cfg_get: Any = _cfg_fallback_get  # replaced by real config below
    try:
        from hfpapers.config import get as _cfg_get
        cfg_get = _cfg_get

        base = Path(_cfg_get("paths.data_dir", "data")).expanduser().resolve()
        pdf_dir = Path(_cfg_get("paths.pdf_dir", str(base / "pdfs"))).expanduser().resolve()
        if not pdf_dir.is_absolute():
            import hfpclawer as _hfp
            pdf_dir = Path(_hfp.__file__).parent.parent / pdf_dir
    except Exception:
        pdf_dir = Path("data/pdfs").resolve()

    pdf_dir.mkdir(parents=True, exist_ok=True)
    pdf_target = pdf_dir / f"{aid}.pdf"
    if pdf_target.exists() and pdf_target.stat().st_size == pdf_size:
        console.print(f"  ✓ Already exists (same size): {pdf_target}")
    else:
        try:
            shutil.copy2(zotero_pdf, str(pdf_target))
            console.print(f"  ✓ Copied → {pdf_target}")
        except (OSError, shutil.Error):
            # Fallback: use copyfile if sendfile fails (e.g., special fs)
            shutil.copyfile(zotero_pdf, str(pdf_target))
            console.print(f"  ✓ Copied (fallback) → {pdf_target}")

    # ── Step 4: CrossRef lookup (DOI + ORCID) ──
    console.print("[dim]   CrossRef DOI + ORCID lookup...[/dim]")
    crossref_doi = ""
    crossref_orcids: dict[str, str] = {}
    try:
        from hfpapers.paper_store import get_crossref

        cr = get_crossref()
        cr_info = cr.arxiv_to_details(aid)
        if cr_info and cr_info.get("doi"):
            crossref_doi = cr_info["doi"]
            crossref_orcids = cr_info.get("orcids", {})
            console.print(f"  ✓ DOI: {crossref_doi}")
            if crossref_orcids:
                for name, orcid in crossref_orcids.items():
                    console.print(f"  ✓ ORCID {name}: {orcid}")
            if cr_info.get("venue"):
                arxiv_categories = arxiv_categories or cr_info["venue"]
        else:
            console.print("  - No CrossRef match for this arXiv ID")
    except Exception as e:
        console.print(f"  [yellow]⚠️  CrossRef: {e}[/yellow]")

    # ── Step 5: convert PDF → Markdown ──
    console.print("[dim] 5/7 Converting PDF → Markdown...[/dim]")
    md_text = ""
    md_ok = False
    md_target: Path | None = None
    try:
        import pymupdf4llm

        raw_md = pymupdf4llm.to_markdown(str(zotero_pdf))
        if isinstance(raw_md, list):
            md_text = "\n\n".join(p.get("text", "") for p in raw_md if isinstance(p, dict))
        else:
            md_text = str(raw_md)

        try:
            _mdd = Path(cfg_get("paths.md_dir", "mds")).expanduser().resolve()
        except Exception:
            _mdd = Path("data/mds").resolve()
        md_target = _mdd / f"{aid}.md"
        md_target.parent.mkdir(parents=True, exist_ok=True)
        md_target.write_text(md_text, encoding="utf-8")
        md_ok = True
        console.print(f"  ✓ MD saved: {md_target} ({len(md_text)} chars)")
    except Exception as e:
        console.print(f"  [yellow]⚠️  MD conversion skipped: {e}[/yellow]")

    # ── Step 6: ingest into paper_store ──
    console.print("[dim] 6/7 Writing to paper_store...[/dim]")
    sf_id = None
    try:
        from hfpapers.paper_store import ensure_paper

        sf_id, is_new = ensure_paper(
            arxiv_id=aid,
            title=arxiv_title,
            abstract=arxiv_abstract,
            doi=crossref_doi,
            venue=arxiv_categories.split(",")[0].strip() if arxiv_categories else "",
            source="zotero-ingest",
        )
        status_str = "🆕 new" if is_new else "♻️ existing"
        console.print(f"  ✓ sf_id={sf_id} ({status_str})")
    except Exception as e:
        console.print(f"  [yellow]⚠️  paper_store write: {e}[/yellow]")

    # ── Step 7: extract annotations from PDF ──
    console.print("[dim] 7/7 Extracting PDF annotations...[/dim]")
    annotations_md = ""
    try:
        from hfpclawer.zotero.annotations import extract_pdf_annotations, format_markdown

        anns = extract_pdf_annotations(zotero_pdf)
        if anns:
            annotations_md = format_markdown(anns, title=arxiv_title, parent_key=parent_key)
            console.print(f"  ✓ {len(anns)} annotations extracted")
        else:
            console.print("  - No annotations found")
    except Exception as e:
        if verbose:
            console.print(f"  [yellow]⚠️  Annotations: {e}[/yellow]")

    # ── Write wiki/raw/papers/{aid}.md ──
    wiki_path: Path | None = None
    if not no_wiki:
        console.print("[dim] 6/6 Writing wiki/raw paper note...[/dim]")

        # Compute SHA256 of PDF
        pdf_sha = sha256(pdf_target.read_bytes()).hexdigest() if pdf_target.exists() else ""

        # Build wiki frontmatter + body
        wiki_lines = []
        wiki_lines.append("---")
        wiki_lines.append(f"source_url: https://arxiv.org/abs/{aid}")
        wiki_lines.append(f"ingested: {datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}")
        wiki_lines.append(f"sha256: {pdf_sha}")
        if arxiv_categories:
            wiki_lines.append(f"categories: [{arxiv_categories}]")
        wiki_lines.append("---")
        wiki_lines.append("")
        wiki_lines.append(f"# {arxiv_title}")
        wiki_lines.append("")
        if arxiv_authors:
            wiki_lines.append(f"**Authors:** {arxiv_authors}")
        wiki_lines.append(f"**arXiv:** [{aid}](https://arxiv.org/abs/{aid})")
        if arxiv_categories:
            wiki_lines.append(f"**Subjects:** {arxiv_categories}")
        wiki_lines.append("")
        wiki_lines.append(f"**Zotero key:** `{parent_key}`")
        if crossref_doi:
            wiki_lines.append(f"**DOI:** [{crossref_doi}](https://doi.org/{crossref_doi})")
        if crossref_orcids:
            wiki_lines.append("**ORCIDs:**")
            for name, orcid in crossref_orcids.items():
                wiki_lines.append(f"  - {name}: [{orcid}]({orcid})")
        wiki_lines.append("")

        # Add abstract if available
        if arxiv_abstract:
            wiki_lines.append("## Abstract")
            wiki_lines.append("")
            wiki_lines.append(arxiv_abstract[:2000])
            wiki_lines.append("")

        # Placeholder for analysis notes
        wiki_lines.append("## Notes")
        wiki_lines.append("")
        wiki_lines.append("*[AI analysis goes here]*")
        wiki_lines.append("")

        # Add annotations
        if annotations_md:
            wiki_lines.append("---")
            wiki_lines.append("")
            wiki_lines.append(annotations_md)

        wiki_content = "\n".join(wiki_lines)

        # Determine output path
        if output:
            wiki_path = Path(output)
        else:
            wiki_path = Path.home() / "wiki" / "raw" / "papers" / f"{aid}.md"
        wiki_path.parent.mkdir(parents=True, exist_ok=True)
        wiki_path.write_text(wiki_content, encoding="utf-8")
        console.print(f"  ✓ Wiki note → {wiki_path} ({len(wiki_content)} chars)")

    # ── Summary ──
    console.print("\n[bold green]✅ Ingest complete[/bold green]")
    if sf_id:
        console.print(f"  paper_store:  sf_id={sf_id}")
    console.print(f"  PDF:          {pdf_target}")
    if md_ok and md_target:
        console.print(f"  Markdown:     {md_target}")
    if wiki_path:
        console.print(f"  Wiki note:    {wiki_path}")
    if annotations_md:
        console.print(f"  Annotations:  {len(anns)} items")
    if crossref_doi:
        console.print(f"  DOI:          {crossref_doi}")
    if crossref_orcids:
        for name, orcid in crossref_orcids.items():
            console.print(f"  ORCID:        {name} → {orcid}")
    console.print(f"  Zotero key:   {parent_key}")
    console.print(f"  Title:        {arxiv_title[:80]}...")
    console.print(f"  Authors:      {arxiv_authors[:80]}...")

    # Offer to open in browser
    console.print(f"\n[dim]🔗 https://arxiv.org/abs/{aid}[/dim]")
