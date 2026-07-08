#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""cli_zotero.py — hfpclawer zotero CLI subcommand.

Registers 'hfpclawer zotero {search,list,get,tags,check}' for READ operations
against Zotero's local HTTP API via pyzotero.
"""

from __future__ import annotations

import logging

from rich.console import Console
from rich.table import Table

logger = logging.getLogger("hfpclawer.cli_zotero")
console = Console()


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
            top_items = zc.top(limit=1)
            console.print(f"  Tags:  {len(tags)}")
            console.print(f"  Items: accessible (no total-count from local API)")
        except Exception:
            pass
    else:
        console.print("[red]❌ Cannot reach Zotero local API (localhost:23119)[/red]")
        console.print("  Make sure Zotero is running and 'Allow other applications' is enabled.")


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
    meta = item.get("meta", {})

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
    """
    from hfpclawer.zotero.connector import (
        ZoteroConnector,
        ConnectorError,
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

    # POST to Zotero
    uri = paper.get("url", "") or f"https://arxiv.org/abs/{resolved_id or ''}"
    console.print(f"[dim]Sending to Zotero via /connector/saveItems...[/dim]")

    try:
        conn = ZoteroConnector()
        result = conn.save_items([item], uri=uri)

        if result.get("status") == 201:
            console.print(f"[green]✅ Pushed to Zotero![/green]")
            console.print(f"  Session:  {result['session_id'][:24]}...")
            console.print(f"  Title:    {item['title'][:60]}")
            console.print(f"  Tags:     {', '.join(t['tag'] for t in item['tags'])}")
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
) -> None:
    """Batch push un-pushed papers from paper_store to Zotero.

    Scans paper_store for papers whose source matches the filter
    and have not been pushed yet (no Zotero record recorded).

    Args:
        source_filter: Only push papers with this source prefix (default: "cron:")
        limit: Max papers to push in one batch (default: 10).
        dry_run: Just show what would be pushed.
    """
    from hfpclawer.zotero.connector import ZoteroConnector, ConnectorError
    try:
        from hfpapers.paper_store import get_store
        store = get_store()
    except Exception as e:
        console.print(f"[red]❌ Cannot access paper_store: {e}[/red]")
        return

    # Get candidates from paper_store
    with store._conn() as conn:
        rows = conn.execute(
            """SELECT p.sf_id, p.title, p.source FROM papers p
               WHERE p.source LIKE ?1
               ORDER BY p.created_at DESC LIMIT ?2""",
            (f"{source_filter}%", limit),
        ).fetchall()

    if not rows:
        console.print(f"[yellow]No papers match source filter '{source_filter}'[/yellow]")
        return

    # Filter: only push those not yet in Zotero (check by searching for hfpclawer tag)
    from hfpclawer.zotero import ZoteroClient
    zc = ZoteroClient()
    pushed = 0
    skipped = 0
    errors = 0

    console.print(f"[bold]Batch push: {len(rows)} candidates[/bold]")

    for row in rows:
        sf_id = row["sf_id"]
        title = (row["title"] or "")[:60]
        source = row.get("source", "unknown")

        # Get arxiv_id
        ids = store.get_identifiers(sf_id)
        arxiv_id = next(
            (i.id_value for i in ids if i.id_type == "arxiv"), None
        )
        if not arxiv_id:
            logger.debug("Skipping sf_id=%s: no arxiv_id", sf_id)
            skipped += 1
            continue

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
            else:
                errors += 1
                console.print(f"  [red]❌[/red] [{arxiv_id}] {result.get('error', '?')}")
        except ConnectorError:
            errors += 1
            console.print(f"  [red]❌[/red] [{arxiv_id}] Connector unreachable")

    if dry_run:
        console.print(f"\n[yellow]Dry run: {len(rows)} papers ready to push[/yellow]")
        console.print("  Use without --dry-run to actually push.")
    else:
        console.print(f"\n[bold]Batch complete: {pushed} pushed, {skipped} skipped, {errors} errors[/bold]")


def _print_creators_preview(item: dict) -> None:
    """Print creator info for dry-run display."""
    creators = item.get("creators", [])
    if creators:
        names = [f"{c.get('lastName','?')}, {c.get('firstName','?')}" for c in creators[:3]]
        console.print(f"  Authors:  {'; '.join(names)}")
        if len(creators) > 3:
            console.print(f"            ... and {len(creators)-3} more")


def _paper_to_zotero_item_simple(paper: dict) -> dict:
    """Minimal paper-to-Zotero conversion for batch push (avoids full connector import)."""
    from hfpclawer.zotero.connector import paper_to_zotero_item
    return paper_to_zotero_item(paper)
