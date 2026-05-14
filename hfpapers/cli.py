#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ─── CLI Entry ──────────────────────────────
# cli.py — typer CLI for Hermes & OpenCode
# v3.3: Integrated SearchDispatcher async search + tqdm progress display

"""
Usage:
  hfpclawer search           Search + classify + list new papers (async multi-source search)
  hfpclawer download         Download top candidate PDFs (8 concurrent)
  hfpclawer convert          pymupdf4llm convert to Markdown
  hfpclawer full             Full pipeline (search → download → convert)
  hfpclawer dedup            Dedup status
  hfpclawer list|ls          List all papers
  hfpclawer info <arxiv_id>  Show paper details
  hfpclawer sniff            LLM-driven paper analysis (analyze new paper abstracts)
  hfpclawer analyze          LLM analysis of downloaded PDFs
  hfpclawer wiki             Generate Wiki pages
  hfpclawer store            Paper store management
  hfpclawer audit            Data audit (arxiv_meta + Paper Store)
  hfpclawer check            Check latest papers
  hfpclawer config           View current configuration
  hfpclawer mcp              Start MCP Server
  hfpclawer stats            Search statistics
"""

import json
import logging
import time
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
    TimeRemainingColumn,
)
from rich.table import Table

from hfpapers.config import get, load_config
from hfpapers.hardware import HardwareProbe

app = typer.Typer(name="hfpclawer", help="HF Papers crawler + Wiki integration")
logger = logging.getLogger("hfpclawer")
console = Console()


def _version_callback(value: bool):
    if value:
        from hfpapers import __version__

        console.print(f"hfpclawer v{__version__}")
        raise typer.Exit()


@app.callback()
def main_callback(
    verbose: bool = typer.Option(False, "--verbose", "-v"),
    version: bool = typer.Option(
        False,
        "--version",
        help="Show version and exit",
        callback=_version_callback,
        is_eager=True,
    ),
):
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )


def _get_probe() -> HardwareProbe:
    return HardwareProbe()


# ════════════════════════════════════════════
# Subcommands
# ════════════════════════════════════════════


@app.command()
def search(
    max_pages: int = typer.Option(3, "--max-pages", "-p", help="Pages per dimension"),
    threshold: int = typer.Option(30, "--threshold", "-t", help="Relevance threshold"),
    dry_run: bool = typer.Option(
        False, "--dry-run", "-n", help="Search + display only, don't save"
    ),
    show_all: bool = typer.Option(
        False, "--all", "-a", help="Show all results (including low relevance)"
    ),
):
    """Search HF Papers → arXiv verify → classify

    Uses SearchDispatcher async multi-source concurrent search (HF CLI, arXiv local/API, OpenReview).
    """
    from hfpapers.evolved import DedupEngine, HFPapersCrawler, RelevanceDetector

    hw = _get_probe()
    console.print(f"[dim]{hw.summary()}[/dim]")

    dedup = DedupEngine()
    detector = RelevanceDetector()
    clawler = HFPapersCrawler(dedup=dedup, detector=detector)

    start_t = time.time()
    try:
        papers = clawler.crawl(max_pages=max_pages)
    except KeyboardInterrupt:
        console.print()
        console.print("[yellow]Search interrupted by user (Ctrl+C).[/yellow]")
        return
    elapsed = time.time() - start_t

    if not show_all:
        papers = [p for p in papers if p.relevance >= threshold]

    # Category stats
    by_cat: dict[str, list] = {}
    for p in papers:
        cat = p.categories[0] if p.categories else "unknown"
        by_cat.setdefault(cat, []).append(p)

    # Rich table
    table = Table(title=f"📄 New papers ({len(papers)} in {elapsed:.1f}s)")
    table.add_column("Rel", style="cyan", justify="right")
    table.add_column("arXiv ID", style="blue")
    table.add_column("Title", style="white")
    table.add_column("Cat", style="green")
    table.add_column("Code", style="yellow")

    for p in sorted(papers, key=lambda x: x.relevance, reverse=True):
        code = "📦" if p.code_url else ""
        cat = p.categories[0] if p.categories else ""
        table.add_row(
            str(p.relevance),
            p.arxiv_id,
            p.title[:70],
            cat[:8],
            code,
        )
    console.print(table)

    if not dry_run and papers:
        from hfpapers.evolved import save_candidates

        path = save_candidates(papers)
        console.print(f"[green]💾 Candidate list: {path}[/green]")


@app.command()
def download(
    limit: int = typer.Option(20, "--limit", "-l", help="Max papers to download"),
):
    """Download candidate paper PDFs

    Uses AsyncPdfDownloader with 8 concurrent downloads, auto-convert to Markdown.
    """
    from hfpapers.evolved import DedupEngine, PaperDownloader, load_candidates

    dedup = DedupEngine()
    downloader = PaperDownloader(dedup=dedup)
    candidates = load_candidates()
    if not candidates:
        console.print("[red]❌ No candidate list, run hfpclawer search first[/red]")
        raise typer.Exit(1)

    papers = candidates[:limit]
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        TimeRemainingColumn(),
    ) as progress:
        task = progress.add_task(f"📥 Downloading {len(papers)} PDFs...", total=len(papers))
        downloader.download_batch(papers)
        progress.update(task, completed=len(papers))
    console.print("[green]✅ Download complete[/green]")


@app.command()
def convert(
    to_wiki: bool = typer.Option(
        False, "--to-wiki", "-w", help="Sync converted MD to wiki/raw/papers"
    ),
):
    """pymupdf4llm convert PDF → Markdown"""
    hw = _get_probe()
    if not hw.use_pdf_converter:
        console.print("[yellow]⚠️  pymupdf4llm unavailable, skipping conversion[/yellow]")
        raise typer.Exit(0)

    from hfpapers.evolved import convert_pdfs

    count = convert_pdfs(to_wiki=to_wiki)
    console.print(f"[green]✅ Converted {count} papers[/green]")
    if to_wiki:
        console.print("[green]  📋 Synced to wiki/raw/papers[/green]")


@app.command()
def full(
    max_pages: int = typer.Option(3, "--max-pages", "-p", help="Pages per dimension"),
    threshold: int = typer.Option(30, "--threshold", "-t", help="Relevance threshold"),
    limit: int = typer.Option(20, "--limit", "-l", help="Download limit"),
    skip_convert: bool = typer.Option(False, "--skip-convert", help="Skip PDF→MD conversion"),
    to_wiki: bool = typer.Option(
        True, "--to-wiki/--no-wiki", help="Sync converted MD to wiki/raw/papers"
    ),
):
    """Full pipeline: search → download → convert

    Uses SearchDispatcher async search + AsyncPdfDownloader concurrent download.
    """
    from hfpapers.evolved import HFPapersCrawler

    HFPapersCrawler  # Trigger import

    start_t = time.time()

    # Step 1: Search
    console.rule("[bold cyan]Step 1/3: Search arXiv papers[/bold cyan]")
    search(max_pages=max_pages, threshold=threshold, dry_run=False)

    candidates_path = Path(get("paths.data_dir", "data")).expanduser() / "candidates_latest.json"
    if not candidates_path.exists():
        console.print("[red]❌ Search produced no candidates, aborting[/red]")
        raise typer.Exit(0)

    # Step 2: Download
    if limit > 0:
        console.rule("[bold cyan]Step 2/3: Download PDFs[/bold cyan]")
        download(limit=limit)  # type: ignore[call-arg]  # noqa: F811

    # Step 3: Convert
    if not skip_convert:
        hw = _get_probe()
        if hw.use_pdf_converter:
            console.rule("[bold cyan]Step 3/3: PDF → Markdown[/bold cyan]")
            convert()
        else:
            console.print("[yellow]⚠️  Skipping conversion (pymupdf4llm unavailable)[/yellow]")

    total_elapsed = time.time() - start_t
    console.print(f"\\n[bold green]✅ Full pipeline complete ({total_elapsed:.0f}s)[/bold green]")


@app.command()
def batch(
    limit: int = typer.Option(50, "--limit", "-l", help="Max papers to process"),
    priority: str = typer.Option(
        "P0", "--priority", "-p", help="Priority tier: P0(relevance≥60) P1(≥30) P2(all pending)"
    ),
    skip_convert: bool = typer.Option(False, "--skip-convert", help="Skip PDF→MD conversion"),
    no_wiki: bool = typer.Option(False, "--no-wiki", help="Skip wiki sync"),
):
    """Batch download from paper_store queue (new DownloadQueue)

    Pulls pending papers from paper_store by priority, downloads PDFs,
    converts to Markdown, and optionally syncs to wiki/raw/papers.

    Priority tiers:
      P0 — relevance ≥ 60 (immediate, high-value papers)
      P1 — relevance 30-59 (medium priority)
      P2 — all remaining pending

    Uses AsyncPdfDownloader with up to 8 concurrent downloads.
    """
    from hfpapers.download_queue import batch_download_cli

    hw = _get_probe()
    console.print(f"[dim]🔧 {hw.summary()}[/dim]")

    summary = batch_download_cli(
        limit=limit,
        priority=priority,
        skip_convert=skip_convert,
        to_wiki=not no_wiki,
    )

    if summary.total == 0:
        # pending is intentionally not used here; comment documents intent
        console.print("[yellow]No pending papers in paper_store[/yellow]")
        # Show queue status
        from hfpapers.download_queue import DownloadQueue

        q = DownloadQueue()
        counts = q.count_pending()
        for status, count in counts.items():
            console.print(f"  [{status}] {count}")
    else:
        console.print("[bold green]✅ Batch complete[/bold green]")
        console.print(f"  {summary.summary_line}")
        if summary.errors:
            console.print(f"[red]  Errors ({len(summary.errors)}):[/red]")
            for e in summary.errors[:5]:
                console.print(f"    ❌ {e}")
            if len(summary.errors) > 5:
                console.print(f"    ... and {len(summary.errors) - 5} more")


@app.command()
def audit(
    action: str = typer.Argument("data", help="data | ops | stats | events | batch | paper"),
    arg: str = typer.Argument("", help="arxiv_id / batch_id / since"),
    limit: int = typer.Option(20, "--limit", "-l", help="Result limit"),
):
    """Audit & data quality inspection

    Two audit engines:
      data  — source data audit (arxiv_meta DB, paper_store quality) [default]
      ops   — download/convert/wiki operation trail (AuditTrail events)

    Ops sub-actions:
      stats  — aggregate event counts
      events — recent operation events
      batch  — summary for a specific batch_id (omit arg for latest)
      paper  — all events for a specific arxiv_id

    Examples:
      hfpclawer audit data           # Data source audit (default)
      hfpclawer audit ops stats      # Operation event counts
      hfpclawer audit ops events -l 10
      hfpclawer audit ops batch      # Latest batch summary
      hfpclawer audit ops paper 2001.08361
    """
    if action == "data":
        # ── Data source audit (arxiv_meta DB + paper_store quality) ──
        from hfpclawer.audit import (
            format_full_audit_report,
            run_full_audit,
        )

        report = run_full_audit()
        console.print(format_full_audit_report(report))

    elif action == "ops":
        # ── Operation trail audit (AuditTrail events) ──
        from hfpapers.logger import get_audit as get_op_audit

        a = get_op_audit()
        sub = arg or "stats"

        if sub == "stats":
            stats = a.stats()
            table = Table(title="📊 Operation Audit Statistics")
            table.add_column("Metric", style="cyan")
            table.add_column("Value", style="white")
            table.add_row("Total events", str(stats["total_events"]))
            table.add_row("Total failures", str(stats["total_failures"]))
            for event, cnt in sorted(stats["by_event"].items(), key=lambda x: -x[1]):
                table.add_row(f"  {event}", str(cnt))
            console.print(table)

        elif sub == "events":
            events = a.query(limit=limit)
            if not events:
                console.print("[yellow]No events found[/yellow]")
                return
            table = Table(title=f"🕐 Recent {len(events)} events")
            table.add_column("Time", style="dim", width=19)
            table.add_column("Event", style="cyan", width=18)
            table.add_column("arXiv ID", style="blue", width=15)
            table.add_column("Batch", style="green", width=16)
            table.add_column("Status", style="white")
            for e in events:
                status = e["status"] or ""
                if status == "failed":
                    status = f"[red]{status}[/red]"
                elif status == "done":
                    status = f"[green]{status}[/green]"
                table.add_row(
                    e["event_time"][:19],
                    e["event"],
                    e["arxiv_id"],
                    e["batch_id"],
                    status,
                )
            console.print(table)

        elif sub == "batch":
            batch_id = arg
            if not batch_id:
                batch_id = a.latest_batch()
                if not batch_id:
                    console.print("[yellow]No batches found[/yellow]")
                    return
                console.print(f"[dim]Auto: latest batch = {batch_id}[/dim]")
            summary = a.batch_summary(batch_id)
            table = Table(title=f"📦 Batch: {summary['batch_id']}")
            table.add_column("Event", style="cyan")
            table.add_column("Status", style="white")
            table.add_column("Count", style="yellow", justify="right")
            for e in summary["events"]:
                table.add_row(e["event"], e["status"], str(e["cnt"]))
            console.print(table)

        elif sub == "paper":
            pid = arg  # arxiv_id
            if not pid:
                console.print("[red]❌ Requires arxiv_id argument[/red]")
                raise typer.Exit(1)
            events = a.query(arxiv_id=pid, limit=limit)
            if not events:
                console.print(f"[yellow]No events for {pid}[/yellow]")
                return
            table = Table(title=f"📄 Events for {pid}")
            table.add_column("Time", style="dim", width=19)
            table.add_column("Event", style="cyan", width=18)
            table.add_column("Batch", style="green", width=16)
            table.add_column("Status", style="white")
            for e in events:
                status = e["status"] or ""
                if status == "failed":
                    status = f"[red]{status}[/red]"
                elif status == "done":
                    status = f"[green]{status}[/green]"
                table.add_row(
                    e["event_time"][:19],
                    e["event"],
                    e["batch_id"],
                    status,
                )
            console.print(table)

        else:
            console.print(
                f"[red]❌ Unknown ops sub-action: {sub}. Use stats|events|batch|paper[/red]"
            )

    elif action in ("stats", "events", "batch", "paper"):
        # Shorthand: allow without "ops" prefix for legacy compat
        from hfpapers.logger import get_audit as get_op_audit

        a = get_op_audit()

        if action == "stats":
            stats = a.stats()
            table = Table(title="📊 Operation Audit Statistics")
            table.add_column("Metric", style="cyan")
            table.add_column("Value", style="white")
            table.add_row("Total events", str(stats["total_events"]))
            table.add_row("Total failures", str(stats["total_failures"]))
            for event, cnt in sorted(stats["by_event"].items(), key=lambda x: -x[1]):
                table.add_row(f"  {event}", str(cnt))
            console.print(table)
        elif action == "batch":
            batch_id = arg or a.latest_batch()
            if not batch_id:
                console.print("[yellow]No batches found[/yellow]")
                return
            if arg == "":
                console.print(f"[dim]Auto: latest batch = {batch_id}[/dim]")
            summary = a.batch_summary(batch_id)
            table = Table(title=f"📦 Batch: {summary['batch_id']}")
            table.add_column("Event", style="cyan")
            table.add_column("Status", style="white")
            table.add_column("Count", style="yellow", justify="right")
            for e in summary["events"]:
                table.add_row(e["event"], e["status"], str(e["cnt"]))
            console.print(table)
        elif action == "paper":
            if not arg:
                console.print("[red]❌ Requires arxiv_id[/red]")
                raise typer.Exit(1)
            events = a.query(arxiv_id=arg, limit=limit)
            if not events:
                console.print(f"[yellow]No events for {arg}[/yellow]")
                return
            table = Table(title=f"📄 Events for {arg}")
            table.add_column("Time", style="dim", width=19)
            table.add_column("Event", style="cyan", width=18)
            table.add_column("Batch", style="green", width=16)
            table.add_column("Status", style="white")
            for e in events:
                status = e["status"] or ""
                if status == "failed":
                    status = f"[red]{status}[/red]"
                elif status == "done":
                    status = f"[green]{status}[/green]"
                table.add_row(e["event_time"][:19], e["event"], e["batch_id"], status)
            console.print(table)
        else:
            # action == "events"
            events = a.query(limit=limit)
            if not events:
                console.print("[yellow]No events found[/yellow]")
                return
            table = Table(title=f"🕐 Recent {len(events)} events")
            table.add_column("Time", style="dim", width=19)
            table.add_column("Event", style="cyan", width=18)
            table.add_column("arXiv ID", style="blue", width=15)
            table.add_column("Batch", style="green", width=16)
            table.add_column("Status", style="white")
            for e in events:
                status = e["status"] or ""
                if status == "failed":
                    status = f"[red]{status}[/red]"
                elif status == "done":
                    status = f"[green]{status}[/green]"
                table.add_row(
                    e["event_time"][:19], e["event"], e["arxiv_id"], e["batch_id"], status
                )
            console.print(table)

    else:
        console.print(f"[red]❌ Unknown action: {action}. Use data or ops[/red]")


@app.command()
def dedup():
    """View dedup statistics"""
    from hfpapers.evolved import DedupEngine

    d = DedupEngine()
    pdf_dir = Path(get("paths.pdf_dir", "pdfs")).expanduser()
    md_dir = Path(get("paths.md_dir", "mds")).expanduser()

    stats = Table(title="📊 Dedup Statistics")
    stats.add_column("Metric", style="cyan")
    stats.add_column("Value", style="white")
    stats.add_row("Dedup records", str(d.count))
    stats.add_row("PDF files", str(len(list(pdf_dir.glob("*.pdf")))))
    stats.add_row("MD files", str(len(list(md_dir.glob("*.md")))))
    console.print(stats)


@app.command(name="list")
def list_papers(
    limit: int = typer.Option(20, "--limit", "-l", help="Display count"),
    category: Optional[str] = typer.Option(None, "--category", "-c", help="Category filter"),
):
    """List crawled papers"""
    dedup_path = Path(get("paths.global_dedup")).expanduser()
    if not dedup_path.exists():
        console.print("[red]❌ Dedup file not found[/red]")
        raise typer.Exit(1)

    with open(dedup_path) as f:
        data = json.load(f)
    papers = data.get("papers", {})

    table = Table(title=f"📚 Papers ({len(papers)})")
    table.add_column("#", style="dim", justify="right")
    table.add_column("arXiv ID", style="blue")
    table.add_column("Title", style="white")
    table.add_column("Code", style="yellow")

    count = 0
    for i, (aid, info) in enumerate(reversed(list(papers.items())), 1):
        if category and category.lower() not in json.dumps(info.get("categories", [])).lower():
            continue
        code = "📦" if info.get("has_code") == "yes" else ""
        table.add_row(str(count + 1), aid, info.get("title", "")[:65], code)
        count += 1
        if count >= limit:
            break
    if table.rows:
        console.print(table)
    else:
        console.print("[yellow]No matching papers[/yellow]")


@app.command()
def info(arxiv_id: str):
    """Lookup a single paper"""
    dedup_path = Path(get("paths.global_dedup")).expanduser()
    with open(dedup_path) as f:
        data = json.load(f)
    p = data.get("papers", {}).get(arxiv_id)
    if not p:
        console.print(f"[red]❌ {arxiv_id} not found[/red]")
        raise typer.Exit(1)
    console.print_json(data=p)


@app.command()
def stats():
    """Search statistics — SearchQueue task completion"""
    from hfpapers.evolved import DedupEngine

    d = DedupEngine()
    hw = _get_probe()
    store_stats = {}
    try:
        from hfpapers.paper_store import store_stats as ss

        store_stats = ss()
    except Exception:
        pass

    table = Table(title="📊 System Statistics")
    table.add_column("Metric", style="cyan")
    table.add_column("Value", style="white")
    table.add_row("Dedup records", str(d.count))
    table.add_row("Search queries", str(len(get("search.queries", []))))
    table.add_row("Paper Store papers", str(store_stats.get("papers_total", "N/A")))
    table.add_row("Paper Store verified", str(store_stats.get("papers_verified", "N/A")))
    for k, v in hw.__dict__.items():
        table.add_row(f"HW.{k}", str(v))
    console.print(table)


@app.command()
def config():
    """View current configuration"""
    cfg = load_config()
    console.print_json(data=cfg)


@app.command()
def store(
    action: str = typer.Argument("stats", help="stats | ensure | search | export | verify | ids"),
    arg: str = typer.Argument("", help="Argument: keyword(for search) / format(for export)"),
    arxiv_id: str = typer.Option("", "--aid", "-a", help="arXiv ID"),
    title: str = typer.Option("", "--title", "-t", help="Paper title"),
    keyword: str = typer.Option("", "--keyword", "-k", help="Search keyword"),
    limit: int = typer.Option(20, "--limit", "-l", help="Result limit"),
):
    """Paper store management (SQLite + Snowflake ID + Crossref)"""
    from hfpapers.paper_store import ensure_paper, get_crossref, get_store, store_stats

    store_obj = get_store()

    if action == "stats":
        ss = store_stats()
        table = Table(title="📊 Paper Store Statistics")
        table.add_column("Metric", style="cyan")
        table.add_column("Value", style="white")
        table.add_row("Total papers", str(ss["papers_total"]))
        table.add_row("Verified", str(ss["papers_verified"]))
        table.add_row("With code", str(ss["papers_with_code"]))
        table.add_row("Total identifiers", str(ss["identifiers_total"]))
        for t, c in ss["identifiers_by_type"].items():
            table.add_row(f"  Identifier: {t}", str(c))
        console.print(table)

    elif action == "ensure":
        if not arxiv_id:
            console.print("[red]❌ Requires --aid[/red]")
            raise typer.Exit(1)
        sf_id, is_new = ensure_paper(arxiv_id, title=title, source="cli")
        paper = store_obj.get_paper_by_id(sf_id)
        ids = store_obj.get_identifiers(sf_id) or []
        console.print(f"📝 ID(sf_id={sf_id}, new={is_new})")
        if paper is not None:
            console.print(f"  Title: {paper.title}")
            console.print(f"  Verified: {'✅' if paper.verified else '❌'}")
        else:
            console.print("  [yellow]Paper record not found[/yellow]")
        for i in ids:
            console.print(f"  {i.id_type}: {i.id_value} (conf={i.confidence})")

    elif action == "search":
        papers = store_obj.search_papers(keyword or arg, limit=limit)
        table = Table(title=f"📚 Found {len(papers)} papers")
        table.add_column("Verified", style="green")
        table.add_column("Rel", style="cyan", justify="right")
        table.add_column("Title", style="white")
        table.add_column("IDs", style="dim")
        for p in papers:
            ids_list = store_obj.get_identifiers(p.sf_id)
            id_str = ", ".join(f"{i.id_type}={i.id_value}" for i in ids_list[:3])
            verified = "✓" if p.verified else " "
            table.add_row(verified, str(p.relevance), p.title[:60], id_str)
        console.print(table)

    elif action == "verify":
        if not arxiv_id:
            console.print("[red]❌ Requires --aid[/red]")
            raise typer.Exit(1)
        cr = get_crossref()
        result = cr.cross_verify(arxiv_id, title if title else arxiv_id)
        if result:
            console.print("[green]✅ Cross-validation successful:[/green]")
            for k, v in result.items():
                console.print(f"  {k}: {v}")
        else:
            console.print("[yellow]❌ No match found[/yellow]")

    elif action == "ids":
        if not arxiv_id:
            console.print("[red]❌ Requires --aid[/red]")
            raise typer.Exit(1)
        paper = store_obj.get_paper_by_identifier("arxiv", arxiv_id)
        if paper:
            ids_list = store_obj.get_identifiers(paper.sf_id)
            console.print(f"Paper: {paper.title}")
            for i in ids_list:
                console.print(f"  {i.id_type}: {i.id_value}")
        else:
            console.print(f"[red]❌ {arxiv_id} not found[/red]")

    elif action == "export":
        fmt = arg or "json"
        if fmt not in ("json", "csv"):
            console.print(f"[red]❌ Unsupported format: {fmt} (json/csv only)[/red]")
            raise typer.Exit(1)
        try:
            out_path = store_obj.export_papers(format=fmt)
            console.print(f"[green]✅ Exported {store_obj.stats()['papers_total']} papers[/green]")
            console.print(f"[dim]   {out_path}[/dim]")
        except ValueError as e:
            console.print(f"[yellow]{e}[/yellow]")
            raise typer.Exit(0)

    else:
        console.print(f"[red]❌ Unknown action: {action}[/red]")


@app.command()
def sniff(
    max_papers: int = typer.Option(10, "--max-papers", "-n", help="Max papers to analyze"),
    threshold: int = typer.Option(30, "--threshold", "-t", help="Relevance threshold"),
):
    """LLM analysis of candidate paper abstracts

    Takes papers from latest candidate list, analyzes abstracts via LLM:
    - Core contribution (Chinese overview)
    - Technical approach
    - Differences from existing work
    - Worth further reading?
    """
    from hfpapers.config import get as cfg_get
    from hfpapers.evolved import load_candidates

    candidates = load_candidates()
    if not candidates:
        console.print("[red]❌ No candidate list, run hfpclawer search first[/red]")
        raise typer.Exit(1)

    papers = [p for p in candidates if p.relevance >= threshold][:max_papers]
    if not papers:
        console.print(f"[yellow]No papers with relevance ≥ {threshold}[/yellow]")
        raise typer.Exit(0)

    console.print(f"[bold cyan]🔍 Analyzing {len(papers)} paper abstracts...[/bold cyan]")

    # Extract summary text
    summaries = []
    for p in papers:
        summary = p.abstract.strip() if p.abstract else ""
        if not summary:
            # Try to fetch from arXiv
            import requests

            try:
                import warnings

                from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning

                warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)
                resp = requests.get(
                    f"http://export.arxiv.org/api/query?id_list={p.arxiv_id}&max_results=1",
                    timeout=15,
                )
                if resp.status_code == 200:
                    soup = BeautifulSoup(resp.text, "lxml")
                    tag = soup.find("summary")
                    if tag:
                        summary = tag.get_text(strip=True)[:1000]
            except Exception:
                pass

        summaries.append(
            {
                "arxiv_id": p.arxiv_id,
                "title": p.title,
                "relevance": p.relevance,
                "abstract": summary[:1000] if summary else "(no abstract)",
            }
        )

    # Build LLM prompt
    prompt_sections = []
    for s in summaries:
        prompt_sections.append(
            f"## {s['arxiv_id']} — {s['title']} (rel={s['relevance']})\n\n"
            f"Abstract: {s['abstract']}\n"
        )

    prompt = (
        "You are an AI4S-focused research assistant analyzing the following paper abstracts. For each paper output:\n"
        "  1. **Core contribution** (1-2 sentences, Chinese)\n"
        "  2. **Technical approach** (keywords)\n"
        "  3. **Worth reading?** ⭐1-5 stars\n"
        "  4. **Rationale** (one sentence)\n\n"
        f"Total {len(prompt_sections)} papers:\n\n" + "\n---\n".join(prompt_sections)
    )

    # Call LLM
    try:
        from litellm import completion

        model = cfg_get("llm.sniff_model", "deepseek/deepseek-chat")
        max_tokens = cfg_get("llm.sniff_max_tokens", 2000)

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
        ) as progress:
            progress.add_task(f"🤖 Calling {model} to analyze abstracts...", total=None)
            resp = completion(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=max_tokens,
                temperature=0.3,
            )

        analysis = resp.choices[0].message.content
        console.print("\n[bold]📋 LLM Analysis Results:[/bold]")
        console.print(analysis)

        # Save to file
        from datetime import datetime

        now = datetime.now().strftime("%Y%m%d_%H%M%S")
        data_dir = Path(cfg_get("paths.data_dir", "data")).expanduser()
        out_path = data_dir / f"sniff_{now}.md"
        with open(out_path, "w") as f:
            f.write(f"# LLM Paper Analysis ({now})\n\n")
            f.write(f"Source: candidates_latest.json (rel≥{threshold}, top {len(papers)})\n\n")
            f.write(analysis)
        console.print(f"[dim]💾 Analysis saved: {out_path}[/dim]")

    except Exception as e:
        console.print(f"[red]❌ LLM call failed: {e}[/red]")
        console.print("\n[yellow]Falling back to local keyword summary mode:[/yellow]")

        # fallback: keyword extraction
        for s in summaries:
            kw = _extract_keywords(s["abstract"])
            console.print(f"\n[bold]{s['arxiv_id']}[/bold] {s['title'][:60]}")
            console.print(f"  Keywords: {', '.join(kw[:10])}")
            console.print(f"  Relevance: {s['relevance']}")


def _extract_keywords(text: str, max_kw: int = 15) -> list[str]:
    """Simple keyword extraction (fallback, when LLM unavailable)"""
    import re

    # Extract technical terms (capitalized first-letter words, hyphenated technical nouns)
    patterns = [
        r"[A-Z][a-z]+(?:[-/][A-Z][a-z]+)*",  # Neural Operator, Physics-Informed
        r"\b(?:PDE|FNO|DeepONet|PINN|GAN|Transformer|CNN|RNN|MLP|ViT|INR|SOTA)\b",
    ]
    words = set()
    for pat in patterns:
        for m in re.finditer(pat, text):
            w = m.group()
            if len(w) >= 3:
                words.add(w)
            if len(words) >= max_kw:
                return sorted(words, key=lambda x: -len(x))
    return sorted(words, key=lambda x: -len(x))[:max_kw]


@app.command()
def mcp(
    port: int = typer.Option(8765, "--port", "-p", help="HTTP mode port"),
    host: str = typer.Option("127.0.0.1", "--host", help="HTTP mode bind host"),
    mode: str = typer.Option("stdio", "--mode", "-m", help="stdio | http"),
):
    """Start MCP Server (Hermes / OpenCode integration)

    stdio mode (default): For Hermes Agent native MCP client.
    http mode: For OpenCode subagent or debugging.
    """
    from hfpapers.mcp_server import run_mcp_server

    if mode == "http":
        console.print(f"🚀 MCP Server → http://{host}:{port}")
    run_mcp_server(host=host, port=port, mode=mode)


# ════════════════════════════════════════════
# Download subcommand — hfpclawer/download pipeline
# ════════════════════════════════════════════


@app.command()
def download(  # noqa: F811 — intentional typer overload for OAI/Kaggle pipeline
    source: str = typer.Option(
        "oai",
        "--source",
        "-s",
        help="Data source: oai (OAI-PMH incremental) | kaggle (Kaggle full)",
    ),
    incremental: bool = typer.Option(
        False, "--incremental", "-i", help="OAI incremental mode (last 1 day only)"
    ),
    all_papers: bool = typer.Option(
        False, "--all", "-a", help="OAI full pull (download all by priority)"
    ),
    tier1: bool = typer.Option(
        False, "--tier1", "-t1", help="OAI download Tier 1 core categories only"
    ),
    force: bool = typer.Option(False, "--force", "-f", help="Kaggle force re-download"),
    status: bool = typer.Option(False, "--status", help="View download progress"),
):
    """Download arXiv metadata (OAI-PMH incremental|full / Kaggle full)"""
    from hfpapers.config import get as cfg_get
    from hfpclawer.download.base import ResumeState

    if status:
        # View status
        db_path = str(
            Path(__file__).resolve().parent.parent / cfg_get("db.path", "data/arxiv_meta.db")
        )
        state = ResumeState(db_path, source).get()
        console.print(f"\n📊 [{source}] Download Status")
        console.print(f"  Status:        {state.get('status', 'unknown')}")

        # Transient progress from .progress.json in temp dir (not SQLite)
        tmp_dir = state.get("extra")
        if tmp_dir:
            try:
                extra = json.loads(tmp_dir) if isinstance(tmp_dir, str) else tmp_dir
            except (json.JSONDecodeError, TypeError):
                extra = None
            if extra and extra.get("tmp_dir"):
                pfile = Path(extra["tmp_dir"]) / ".progress.json"
                if pfile.exists():
                    try:
                        prog = json.loads(pfile.read_text())
                        p = prog.get("progress", "")
                        dm = prog.get("downloaded_mb")
                        tm = prog.get("total_mb")
                        if tm:
                            console.print(f"  Progress:      {p} ({dm:,} MB / {tm:,} MB)")
                        elif dm:
                            console.print(f"  Progress:      {dm:,} MB")
                        else:
                            console.print(f"  Progress:      {p}")
                        console.print(f"  Temp dir:      {prog.get('tmp_dir', '')}")
                    except (OSError, json.JSONDecodeError):
                        pass
        console.print(f"  Fetched:       {state.get('total_fetched', 0):,}")
        console.print(f"  New:           {state.get('total_new', 0):,}")
        console.print(f"  Last updated:  {state.get('last_update', 'never')}")
        checksum = state.get("checksum", "")
        console.print(f"  Checksum:      {checksum if checksum else 'N/A'}")
        error = state.get("error", "")
        if error:
            console.print(f"  Error:         {error[:200]}")
        return

    if source == "oai":
        from hfpclawer.download.oai import OaiPmhDownloader

        dl = OaiPmhDownloader()
        with console.status("[bold cyan]📥 Downloading arXiv OAI-PMH metadata..."):
            total = dl.run(
                incremental=incremental,
                from_date="",
                tier1_only=tier1,
            )
        console.print(f"[green]✅ Download complete: +{total:,} papers[/green]")

    elif source == "kaggle":
        from hfpclawer.download.kaggle import KaggleDownloader

        dl = KaggleDownloader()
        with console.status("[bold cyan]📥 Downloading arXiv dataset from Kaggle..."):
            total = dl.run(force=force)
        if total > 0:
            console.print(f"[green]✅ Kaggle download complete: {total:,} papers[/green]")
        else:
            console.print("[green]✅ Dataset is up to date, no download needed[/green]")

    else:
        console.print(f"[red]❌ Unknown data source: {source} (available: oai, kaggle)[/red]")


# ── Second audit command removed (merged into `audit` above) ──
# The `audit` at line 289 already supports `audit data` for data source audit.
# The duplicate below was merged via the first command's `action="data"` path.


def _import_dummy():
    """Ensure import loaded"""
    pass


@app.command()
def init(
    quick: bool = typer.Option(
        False, "--quick", "-q", help="Quick mode (use defaults, no interaction)"
    ),
    data_dir: str = typer.Option(
        "data", "--data-dir", "-d", help="Data directory for downloads and DB"
    ),
):
    """Initialize config — generate config.yaml + .env.template

    Run once before first use. Creates config.yaml and .env.template
    in the current directory. Use --quick for non-interactive setup.
    """
    import yaml

    cwd = Path.cwd()
    cfg_path = cwd / "config.yaml"
    env_path = cwd / ".env.template"

    # Guard: don't overwrite existing config
    if cfg_path.exists():
        console.print(f"[yellow]⚠️  config.yaml already exists: {cfg_path}[/yellow]")
        console.print("[dim]    Delete it and re-run init, or edit directly[/dim]")
        raise typer.Exit(0)

    if quick:
        # Quick mode: write defaults
        default = {
            "search": {
                "max_per_dim": 50,
                "queries": [
                    {"query": "neural operator", "category": "neural-operator", "priority": 1},
                    {"query": "physics informed", "category": "pinn", "priority": 2},
                    {"query": "pde solver", "category": "pde-solver", "priority": 3},
                ],
            },
            "keywords": {
                "include_high": [
                    "neural operator",
                    "fourier neural operator",
                    "deep operator network",
                    "physics informed",
                    "pde",
                    "partial differential equation",
                    "operator learning",
                ],
                "include_medium": [
                    "scientific machine learning",
                    "sciml",
                    "numerical solver",
                    "meshfree",
                ],
                "exclude": ["quantum", "large language model", "llm", "reinforcement learning"],
            },
            "classification": {
                "threshold_pass": 30,
                "threshold_high": 70,
                "title_similarity_min": 0.40,
            },
            "paths": {
                "data_dir": data_dir,
                "pdf_dir": f"{data_dir}/pdfs",
                "md_dir": f"{data_dir}/mds",
                "global_dedup": f"{data_dir}/crawled.json",
            },
            "db": {
                "path": f"{data_dir}/arxiv_meta.db",
            },
        }
        cfg_path.write_text(yaml.dump(default, default_flow_style=False, allow_unicode=True))
        console.print(f"[green]✅ config.yaml generated: {cfg_path}[/green]")
    else:
        # Interactive wizard
        console.print("[cyan]📝 hfpclawer init wizard[/cyan]")
        console.print("[dim]Press Enter to accept defaults[/dim]\n")

        try:
            _ = input(f"  Project name [{cwd.name}]: ")  # consumed, reserved for future
            data = input(f"  Data directory [{data_dir}]: ") or data_dir
            queries_raw = (
                input("  Search keywords [neural operator, physics informed, pde solver]: ")
                or "neural operator, physics informed, pde solver"
            )
            queries = [
                {"query": q.strip(), "category": "custom", "priority": i + 1}
                for i, q in enumerate(queries_raw.split(","))
            ]
            threshold = int(input("  Relevance threshold (0-100) [30]: ") or "30")

            default = {
                "search": {
                    "max_per_dim": 50,
                    "queries": queries,
                },
                "keywords": {
                    "include_high": [
                        "neural operator",
                        "fourier neural operator",
                        "deep operator network",
                        "physics informed",
                        "pde",
                        "partial differential equation",
                        "operator learning",
                    ],
                    "include_medium": [
                        "scientific machine learning",
                        "sciml",
                        "numerical solver",
                        "meshfree",
                    ],
                    "exclude": ["quantum", "large language model", "llm", "reinforcement learning"],
                },
                "classification": {
                    "threshold_pass": threshold,
                    "threshold_high": min(70, threshold + 40),
                    "title_similarity_min": 0.40,
                },
                "paths": {
                    "data_dir": data,
                    "pdf_dir": f"{data}/pdfs",
                    "md_dir": f"{data}/mds",
                    "global_dedup": f"{data}/crawled.json",
                },
                "db": {
                    "path": f"{data}/arxiv_meta.db",
                },
            }
            cfg_path.write_text(yaml.dump(default, default_flow_style=False, allow_unicode=True))
            console.print(f"[green]✅ config.yaml generated: {cfg_path}[/green]")
        except (EOFError, KeyboardInterrupt):
            console.print()
            console.print("[yellow]⚠️  Init cancelled[/yellow]")
            raise typer.Exit(0)

    # Generate .env.template
    env_template = """# hfpclawer environment variables
# Copy to .env and fill in values:
#   cp .env.template .env

# HuggingFace Token (required for HF Papers search, set your HF token here)
HF_TOKEN=***

# DeepSeek API Key (for LLM analysis, optional, set your DeepSeek API key here)
DEEPSEEK_API_KEY=***

# Ollama endpoint (local LLM, optional)
OLLAMA_API_BASE=http://localhost:11434

# HTTP proxy (optional)
HTTP_PROXY=
HTTPS_PROXY=
"""
    if not env_path.exists():
        env_path.write_text(env_template.lstrip())
        console.print(f"[green]✅ .env.template generated: {env_path}[/green]")
        console.print("[dim]    Copy to .env and fill in API keys: cp .env.template .env[/dim]")
    else:
        console.print("[dim]⏭️  .env.template already exists, skipped[/dim]")

    console.print()
    console.print("[cyan]📖 Next steps:[/cyan]")
    console.print(f"  1. Edit {cfg_path.name} to customize search queries and paths")
    console.print("  2. cp .env.template .env and fill in API keys")
    console.print("  3. hfpclawer search to start finding papers")
    console.print("  Full docs: docs/USAGE.md")


@app.command()
def monitor(
    action: str = typer.Argument("status", help="start | stop | status"),
    interval: int = typer.Option(
        900, "--interval", "-i", help="Poll interval (seconds, default 900=15min)"
    ),
):
    """Background monitor daemon — periodic OAI-PMH incremental download"""
    from hfpapers.config import load_config
    from hfpclawer.download.monitor import MonitorDaemon

    load_config()  # ensure config is loaded
    base_dir = Path(__file__).resolve().parent.parent
    daemon = MonitorDaemon(base_dir=str(base_dir), interval=interval)

    if action == "start":
        if daemon.start():
            console.print(f"[green]✅ MonitorDaemon started (PID={daemon._read_pid()})[/green]")
            console.print(f"[dim]   Log: {daemon.log_path}[/dim]")
        else:
            console.print("[yellow]⚠️  MonitorDaemon already running[/yellow]")

    elif action == "stop":
        if daemon.stop():
            console.print("[green]✅ MonitorDaemon stopped[/green]")
        else:
            console.print("[yellow]⚠️  MonitorDaemon not running[/yellow]")

    elif action == "status":
        st = daemon.status()
        if st["running"]:
            console.print("[green]✅ MonitorDaemon running[/green]")
            console.print(f"  PID:      {st['pid']}")
            console.print(f"  Interval:     {st['interval']}s")
            ds = st.get("download_state", {})
            if ds and "error" not in ds:
                console.print(f"  Download status: {ds.get('status', 'N/A')}")
                console.print(f"  DB papers: {ds.get('total_new', 0):,}")
        else:
            console.print("[yellow]⚠️  MonitorDaemon not running[/yellow]")
        console.print(f"  PID file: {st['pid_file']}")
        console.print(f"  Log file: {st['log_file']}")
