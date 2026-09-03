#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ─── CLI Entry ──────────────────────────────
# cli.py — typer CLI for Hermes & OpenCode
# v3.3: Integrated SearchDispatcher async search + tqdm progress display

"""
Usage:
  hfpclawer version          Show version
  hfpclawer search           Search + classify + list new papers (async multi-source search)
  hfpclawer download         Download top candidate PDFs (8 concurrent)
  hfpclawer convert          pymupdf4llm convert to Markdown
  hfpclawer full             Full pipeline (search -> download -> convert)
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

# Mount verify subcommand
from hfpapers.verify_cli import verify_app

app.add_typer(verify_app, name="verify")
logger = logging.getLogger("hfpclawer")
console = Console()


@app.callback()
def main_callback(
    verbose: bool = typer.Option(False, "--verbose", "-v"),
):
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )


def _get_probe() -> HardwareProbe:
    return HardwareProbe()


@app.command()
def version():
    """Show version and exit"""
    from hfpapers import __version__

    console.print(f"hfpclawer v{__version__}")


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
    search_timeout: float = typer.Option(
        15.0, "--search-timeout", help="Per-source timeout in seconds (default: 15)"
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
    clawler = HFPapersCrawler(dedup=dedup, detector=detector, source_timeout=search_timeout)

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
def convert_tex(
    to_wiki: bool = typer.Option(
        False, "--to-wiki", "-w", help="Sync converted MD to wiki/raw/papers"
    ),
    arxiv_id: str = typer.Option(
        "", "--arxiv-id", "-a", help="Single arXiv ID to convert (default: all pending)"
    ),
    tex_dir: str = typer.Option(
        "",
        "--tex-dir",
        "-d",
        help="Path to tex_src dir with .tar.gz files (default: <repo>/data/tex_src/)",
    ),
):
    """Convert arXiv TeX source → formula-preserving Markdown

    Scans data/tex_src/ for .tar.gz, extracts .tex,
    tries pandoc (best), falls back to Python regex.

    0 LLM, 0 token — pure rule-based conversion.
    LaTeX math preserved as $$...$$, citations as [@key].
    """
    from pathlib import Path

    from hfpapers.tex_converter import cli_convert_tex

    tex_path = Path(tex_dir).expanduser().resolve() if tex_dir else None

    with console.status("[dim]Converting arXiv TeX sources to Markdown...") as status:
        cli_convert_tex(
            to_wiki=to_wiki,
            arxiv_id=arxiv_id or None,
            tex_dir=tex_path,
        )
    console.print("[green]✅ TeX→MD conversion complete[/green]")


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


ACTION_DESCRIPTIONS = {
    "data": "source data audit (arxiv_meta DB, paper_store quality)",
    "ops": "operation trail audit (AuditTrail events)",
    "verify": "citation verification (local → S2 → OpenAlex)",
    "traceability": "full-chain citation traceability (bib → store → notebook → L1/L2/L3)",
    "cron-verify": "batch Crossref verify + retraction check for cron-imported papers",
}

VALID_ACTIONS = list(ACTION_DESCRIPTIONS.keys())


@app.command()
def audit(
    action: str = typer.Argument(
        "data",
        help="| ".join(f"{k}: {v}" for k, v in ACTION_DESCRIPTIONS.items()),
    ),
    arg: str = typer.Argument("", help="arxiv_id / batch_id / citation text"),
    limit: int = typer.Option(20, "--limit", "-l", help="Result limit"),
    source: str = typer.Option(
        "auto",
        "--source",
        help="For verify: citation source (auto|local|s2|openalex)",
    ),
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
        from hfpclawer.audit_deprecated import (
            format_full_audit_report,
            run_full_audit,
        )

        report = run_full_audit()
        console.print(format_full_audit_report(report))

    elif action == "verify":
        # ── Citation verification (L1→L2→L3) ──
        from hfpclawer.audit.l1_local import check_citation_local
        from hfpclawer.audit.l2_s2 import S2Client
        from hfpclawer.audit.l3_openalex import OAClient

        def _format_oa(result: dict) -> str:
            status = result.get("status", "UNKNOWN")
            if status == "VERIFIED":
                title = result.get("title", "?")
                year = result.get("year", "?")
                doi = result.get("doi", "?")
                venue = result.get("venue", "?")
                return (
                    "[green]VERIFIED[/green]  " + title + "\n"
                    "  Year: " + str(year) + "  DOI: " + str(doi) + "  Venue: " + str(venue)
                )
            elif status == "NOT_FOUND":
                return f"[yellow]NOT_FOUND[/yellow]  {result.get('title', '?')[:80]}"
            elif status == "ERROR":
                return f"[red]ERROR[/red]  {result.get('error', '?')}"
            return f"[dim]{status}[/dim]"

        def _do_verify(title: str, src: str) -> dict:
            if src == "openalex" or src == "auto":
                if src == "auto":
                    # Try L1 first, fall back to L3
                    l1 = check_citation_local(title)
                    if l1.get("status") == "VERIFIED":
                        return l1
                oa = OAClient()
                return oa.lookup(title)
            elif src == "s2":
                s2 = S2Client()
                return s2.lookup(title)
            else:
                return check_citation_local(title)

        if not arg:
            console.print("[red][ERR] verify requires citation text as argument[/red]")
            console.print(
                '[dim]  Example: hfpclawer audit verify "Fourier Neural Operator" --source auto[/dim]'
            )
            raise typer.Exit(1)

        with console.status(f"[dim]Verifying citation: {arg[:80]}...[/dim]"):
            result = _do_verify(arg, source)
        console.print(_format_oa(result))

    elif action == "traceability":
        # ── Full-chain traceability (bib → store → notebook → L1) ──
        from hfpclawer.audit.traceability import _detect_repo_name, run_traceability

        repo = arg or _detect_repo_name()
        console.print(f"[cyan]🔍 Running traceability audit for:[/cyan] [bold]{repo}[/bold]")

        with console.status("[dim]Scanning bibliographic references...[/dim]"):
            report = run_traceability(
                repo_name=repo,
                quick=False,
                use_l2_l3=False,
            )

        from hfpclawer.audit.report import print_summary

        print_summary(report)

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

    elif action == "cron-verify":
        # ── Batch cron import verification ──
        from hfpapers.paper_store import get_crossref, get_store
        from hfpclawer.audit.cron_verify import batch_verify, format_report, format_report_json

        since = arg if arg else ""
        retraction_only = False
        force_all = False
        verbose = False
        output_json = False
        # Parse extra options from arg if prefixed
        if arg.startswith("--"):
            parts = arg.split()
            for p in parts:
                if p == "--json":
                    output_json = True
                elif p == "--retraction-only":
                    retraction_only = True
                elif p == "--all":
                    force_all = True
                elif p == "--verbose":
                    verbose = True
                elif p.startswith("--since="):
                    since = p.split("=", 1)[1]
            since = "" if since.startswith("--") else since

        store = get_store()
        cr = get_crossref()
        t0 = time.time()
        with console.status("[dim]Running cron batch verify..."):
            stats = batch_verify(
                store,
                cr,
                since=since,
                retraction_only=retraction_only,
                force_all=force_all,
                verbose=verbose,
            )
        elapsed = time.time() - t0
        if output_json:
            console.print(format_report_json(stats, elapsed))
        else:
            console.print(format_report(stats, elapsed))
        if stats.retractions:
            console.print("[yellow]⚠️  Retractions detected — review above[/yellow]")

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
def cron(
    action: str = typer.Argument(
        "run",
        help="init | check | run | import",
    ),
    arg: str = typer.Argument(
        "",
        help="For init: query string / keywords / --from-config path. For import: source (candidates|jsonl)",
    ),
    name: str = typer.Option(
        "my-domain",
        "--name",
        "-n",
        help="Domain name (for cron init)",
    ),
    query: str = typer.Option(
        "",
        "--query",
        "-q",
        help="arXiv query string (e.g. 'cat:cs.AI+AND+abs:neural+operator')",
    ),
    keywords: str = typer.Option(
        "",
        "--keywords",
        "-k",
        help="Comma-separated keywords (auto-converts to arXiv query)",
    ),
    from_config: str = typer.Option(
        "",
        "--from-config",
        help="Path to existing hfpclawer config YAML",
    ),
    data_dir: str = typer.Option(
        "",
        "--data-dir",
        "-d",
        help="Custom data directory (default: ~/.hfpclawer/data/)",
    ),
    path: str = typer.Option(
        "",
        "--path",
        "-p",
        help="Path to file (for import)",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        "-f",
        help="Force overwrite (for init)",
    ),
    json_output: bool = typer.Option(
        False,
        "--json",
        "-j",
        help="JSON output (for no_agent cron mode)",
    ),
):
    """Cron automation for periodic paper fetch + paper_store import

    Actions:
      init      — Initialize ~/.hfpclawer/ config + scripts
      check     — Show cron configuration status
      run       — Execute cron pipeline (search → import)
      import    — Import papers from candidates/jsonl into paper_store

    Examples:
      hfpclawer cron init --name gsnv --query "cat:physics.ins-det+AND+abs:MFL"
      hfpclawer cron init --keywords "neural operator,physics-informed" --name nn-pde
      hfpclawer cron check
      hfpclawer cron run
      hfpclawer cron run --json
      hfpclawer cron import candidates
      hfpclawer cron import jsonl --path ~/papers.jsonl
    """
    from hfpclawer.cli_cron import cron_check, cron_init, cron_run
    from hfpclawer.cli_cron import cron_import as _cron_import

    if action == "init":
        # Support: arg as query shorthand, or --query/--keywords
        q = arg if arg and not arg.startswith("--") else query
        kw = keywords
        fc = from_config
        if arg and arg.startswith("--"):
            fc = arg
        result = cron_init(
            name=name,
            query=q,
            keywords=kw,
            from_config=fc,
            data_dir=data_dir,
            force=force,
        )
        console.print(result)

    elif action == "check":
        result = cron_check()
        console.print(result)

    elif action == "run":
        result = cron_run(json_output=json_output)
        console.print(result)

    elif action == "import":
        source = arg or "candidates"
        result = _cron_import(source=source, path=path)
        console.print(result)

    else:
        console.print(f"[red]❌ Unknown cron action: {action}. Use init|check|run|import[/red]")


@app.command()
def zotero(
    action: str = typer.Argument(
        "list",
        help="check | list | search | get | tags | tag-report | innovate | children | push | push-batch | annotate | ingest",
    ),
    arg: str = typer.Argument(
        "",
        help="Item key (for get/children), search query (for search), "
        "arxiv_id (for push), or source filter (for push-batch)",
    ),
    limit: int = typer.Option(20, "--limit", "-l", help="Max results"),
    start: int = typer.Option(0, "--start", help="Offset for pagination"),
    tag: str = typer.Option("", "--tag", "-t", help="Filter by tag (or extra tags for push)"),
    item_type: str = typer.Option("", "--item-type", help="Filter by item type"),
    q: str = typer.Option("", "--q", "-q", help="Quick search query"),
    collection: str = typer.Option("", "--collection", help="Collection key (for tags)"),
    aid: str = typer.Option("", "--aid", "-a", help="arXiv ID (for push)"),
    title: str = typer.Option("", "--title", help="Paper title (for push)"),
    dry_run: bool = typer.Option(
        False, "--dry-run", "-n", help="Show what would be pushed without sending"
    ),
    dedup: bool = typer.Option(
        True,
        "--dedup/--no-dedup",
        "-d",
        help="Skip if paper already exists in Zotero (default: True)",
    ),
    with_pdf: bool = typer.Option(
        False,
        "--with-pdf",
        "-p",
        help="Also attach local PDF file to the Zotero item",
    ),
    key: str = typer.Option("", "--key", "-k", help="Zotero item key (for annotate)"),
    fmt: str = typer.Option(
        "markdown",
        "--fmt",
        "--format",
        help="Output format (markdown or json, for annotate)",
    ),
    output: str = typer.Option("", "--output", "-o", help="Save to file (for annotate)"),
    color_hex: str = typer.Option("", "--color-hex", help="Filter by hex color (for annotate)"),
    color_name: str = typer.Option("", "--color-name", help="Filter by color name (for annotate)"),
    export_all: bool = typer.Option(False, "--all", help="Export entire library (for export)"),
    list_formats: bool = typer.Option(
        False, "--list-formats", help="List available export formats"
    ),
    raw: bool = typer.Option(False, "--raw", help="Show raw HTML notes (for note command)"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Verbose output (for ingest)"),
    no_wiki: bool = typer.Option(False, "--no-wiki", help="Skip wiki/raw output (for ingest)"),
):
    """Zotero operations via local API (read) and Connector protocol (write)

    READ actions (local API, port 23119/api/):
      check     — Test Zotero local API connectivity
      list      — List top-level items
      search    — Search items by query
      get       — Get item details by key
      tags      — List all tags
      children  — List children (attachments/notes) of an item

    WRITE actions (Connector protocol, port 23119/connector/):
      push      — Push a paper from paper_store (or direct) to Zotero
      push-batch — Batch push all un-pushed papers from a source domain

    INGEST action:
      ingest    — Zotero local PDF → paper_store + wiki/raw + annotations

    Examples:
      hfpclawer zotero check
      hfpclawer zotero list --limit 10
      hfpclawer zotero list --tag hfpclawer
      hfpclawer zotero search "neural operator" --limit 5
      hfpclawer zotero get ABC123
      hfpclawer zotero tags
      hfpclawer zotero children ABC123
      hfpclawer zotero push 2501.01934           # From paper_store
      hfpclawer zotero push --aid 2501.01934 --dry-run  # Preview
      hfpclawer zotero push --title "My Paper" --tag "my-project"
      hfpclawer zotero push-batch cron:coc        # Batch push cron:coc papers
      hfpclawer zotero push-batch --limit 5 --dry-run
      hfpclawer zotero ingest 2501.01934          # Zotero PDF → wiki/raw
    """
    from hfpclawer.zotero.cli import (
        cmd_annotate,
        cmd_check,
        cmd_children,
        cmd_export,
        cmd_get,
        cmd_ingest,
        cmd_innovate,
        cmd_list,
        cmd_note,
        cmd_push,
        cmd_push_batch,
        cmd_search,
        cmd_tag_report,
        cmd_tags,
    )

    if action == "check":
        cmd_check()
    elif action == "list":
        cmd_list(limit=limit, start=start, tag=tag, item_type=item_type, q=q)
    elif action == "search":
        q = arg or q
        if not q and not tag and not item_type:
            console.print("[yellow]Provide a search query (arg or --q)[/yellow]")
            return
        cmd_search(q=q, limit=limit, tag=tag, item_type=item_type)
    elif action == "get":
        if not arg:
            console.print("[yellow]Provide item key[/yellow]")
            return
        cmd_get(arg)
    elif action == "tags":
        cmd_tags(collection=collection)
    elif action == "children":
        if not arg:
            console.print("[yellow]Provide item key[/yellow]")
            return
        cmd_children(arg)
    elif action == "push":
        # Push single paper: use arg as arxiv_id, or explicit options
        cmd_push(
            arxiv_id=arg,
            aid=aid,
            title=title,
            tag=tag,
            dry_run=dry_run,
            dedup=dedup,
            with_pdf=with_pdf,
        )
    elif action == "push-batch":
        # Batch push: optional source filter
        source_filter = arg or "cron:"
        limit_value = limit
        cmd_push_batch(source_filter=source_filter, limit=limit_value, dry_run=dry_run, dedup=dedup)
    elif action in ("annotate", "ann"):
        # Extract PDF annotations
        cmd_annotate(
            arxiv_id=arg or aid,
            zotero_key=key,
            fmt=fmt,
            output=output,
            color_hex=color_hex,
            color_name=color_name,
        )
    elif action == "export":
        # Export references
        cmd_export(
            arxiv_id=arg or aid,
            zotero_key=key,
            collection_key=collection,
            export_all=export_all,
            fmt=fmt if not list_formats else "list-formats",
            output=output,
        )
    elif action == "note":
        # Read notes
        cmd_note(
            arxiv_id=arg or aid,
            zotero_key=key,
            output=output,
            raw=raw,
        )
    elif action == "ingest":
        # Zotero PDF → paper_store + wiki/raw
        cmd_ingest(
            arxiv_id=arg or aid,
            output=output,
            no_wiki=no_wiki,
            verbose=verbose,
        )
    elif action in ("tag-report", "tagreport", "tag-r"):
        # spaCy tag analysis report
        cmd_tag_report(limit=limit or 200, chart_path=output)
    elif action in ("innovate", "tag"):
        # Extract innovation keywords. Add --dry-run to preview without writing.
        cmd_innovate(
            arxiv_id=arg or aid,
            zotero_key=key,
            dry_run=dry_run,
            push=not dry_run and bool(key or arg),
        )
    else:
        console.print(f"[red]❌ Unknown zotero action: {action}[/red]")


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
def graph(
    action: str = typer.Argument(
        "stats",
        help="build | stats | export | person | community | path | analyze | ingest | ingest-citations | expand-citations | step | geo | viz | map",
    ),
    arg: str = typer.Argument(
        "",
        help="Person node ID (for person) / source (for ingest) / max_depth (for expand-citations) / source node (for path)",
    ),
    arg2: str = typer.Argument(
        "", help="Target node ID (for path) / max_seeds (for expand-citations) / path (for ingest)"
    ),
    limit: int = typer.Option(200, "--limit", "-l", help="Max Zotero items (build)"),
    force: bool = typer.Option(False, "--force", "-f", help="Rebuild from scratch (build)"),
    fmt: str = typer.Option("jsonl", "--format", help="Export format: jsonl | graphml"),
    depth: int = typer.Option(1, "--depth", "-d", help="Ego network depth (person)"),
    top_n: int = typer.Option(20, "--top", "-t", help="Top N results (community/person)"),
    src: str = typer.Option("", "--source", help="Filter by source tag (viz: coc, zotero)"),
    report_fmt: str = typer.Option(
        "markdown", "--report-format", help="Report format: markdown | qmd | json"
    ),
    audit_path: str = typer.Option("", "--audit", help="Audit JSONL path (expand-hub: rank-training trail)"),
    community: bool = typer.Option(False, "--community", help="SimClusters 2-hop community mode (expand-hub)"),
):
    """Knowledge graph operations (v0.10.3).

    Actions: build | stats | export | person | community | path | geo
    Geo sub-actions: geo stats | geo institutions | geo globe | geo enrich orcid
    Map: map [output] | map community [output]
    Viz: viz [style] [output] [--source]
    Stepping: step layer | step all | step config
    """
    from hfpclawer.graph_cli import (
        cmd_analyze,
        cmd_build,
        cmd_community,
        cmd_community_map,
        cmd_enrich_orcid,
        cmd_expand_citations,
        cmd_expand_hub,
        cmd_export,
        cmd_geo_globe,
        cmd_geo_institutions,
        cmd_geo_stats,
        cmd_ingest,
        cmd_ingest_citations,
        cmd_map,
        cmd_path,
        cmd_person,
        cmd_stats,
        cmd_step,
        cmd_viz,
    )

    if action == "build":
        cmd_build(limit=limit, force=force)
    elif action == "stats":
        cmd_stats()
    elif action == "export":
        cmd_export(fmt=fmt, output=arg or "", limit=limit)
    elif action == "person":
        cmd_person(arg, depth=depth, top_n=top_n)
    elif action == "community":
        cmd_community(min_size=arg, top_n=top_n)
    elif action == "path":
        cmd_path(arg, arg2)
    elif action == "map":
        if arg and arg.strip().lower() == "community":
            cmd_community_map(output=arg2 or "", show_edges=True)
        else:
            cmd_map(output=arg or "")
    elif action == "viz":
        cmd_viz(style=arg or "circos", output=arg2 or "", source=src)
    elif action == "ingest":
        cmd_ingest(source=arg or "coc", path=arg2 or "")
    elif action == "ingest-citations":
        cmd_ingest_citations(path=arg or "")
    elif action == "expand-citations":
        cmd_expand_citations(
            max_depth=int(arg or "2"), max_seeds=int(arg2 or "10"), direction="both"
        )
    elif action == "expand-hub":
        # expand-hub [seeds_csv] [max_layers]  (--checkpoint PATH --top-k N --audit PATH --community)
        cmd_expand_hub(
            seeds=arg or "",
            max_layers=int(arg2 or "3"),
            top_k=top_n,
            direction="both",
            checkpoint=src or "",
            audit_path=audit_path,
            community=community,
        )
    elif action == "analyze":
        cmd_analyze(
            source=src,
            community_algo=arg or "leiden",
            top_n=top_n,
            output=arg2 or "",
            output_format=report_fmt,
        )
    elif action == "step":
        if arg in ("show-config", "config"):
            cmd_step(layer="", all_layers=False, show_config=True)
        elif arg in ("all", "--all", "-all"):
            cmd_step(layer="", all_layers=True, show_config=False)
        else:
            cmd_step(layer=arg or "", all_layers=False, show_config=False)
    elif action == "geo":
        sub = arg.strip().lower()
        if sub == "stats":
            cmd_geo_stats()
        elif sub == "institutions":
            cmd_geo_institutions()
        elif sub == "globe":
            # geo globe [projection] — defaults to robinson
            proj = arg2.strip() if arg2 and arg2.strip() else "robinson"
            cmd_geo_globe(output="", projection=proj)
        elif sub in ("enrich", "orcid") or sub == "enrich orcid":
            # geo enrich [orcid] [--force] [--limit N]
            cmd_enrich_orcid(force=force, limit=limit)
        else:
            console.print(
                f"[red]❌ Unknown geo subcommand: '{sub}'. Use geo stats | geo institutions | geo globe | geo enrich orcid.[/red]"
            )
    else:
        console.print(
            f"[red]❌ Unknown graph action: {action}. "
            f"Use build | stats | export | person | community | path | analyze | step.[/red]"
        )


@app.command()
def config():
    """View current configuration"""
    cfg = load_config()
    console.print_json(data=cfg)


@app.command()
def store(
    action: str = typer.Argument("stats", help="stats | ensure | search | export | verify | ids | status | conflicts | suspect | clear-suspect"),
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

    elif action == "status":
        # Single paper (--aid) or summary table (no aid)
        if arxiv_id:
            paper = store_obj.get_paper_by_identifier("arxiv", arxiv_id)
            if not paper:
                console.print(f"[red]❌ {arxiv_id} not found[/red]")
                raise typer.Exit(1)
            st = store_obj.get_status(paper.sf_id)
            color = {"pending": "yellow", "suspect": "red",
                     "verified": "green", "stale": "magenta"}.get(st["status"], "white")
            console.print(f"[{color}]● {st['status']}[/{color}]  {paper.title[:70]}")
            console.print(f"  reason: {st['reason']}")
            console.print(f"  since:  {st['since'] or '-'}   audit_level={st['audit_level']}")
        else:
            summary = store_obj.status_summary()
            total = sum(summary.values())
            table = Table(title=f"📊 Verification Status ({total} papers)")
            table.add_column("Status", style="cyan")
            table.add_column("Count", style="white", justify="right")
            for s in ("pending", "verified", "stale", "suspect"):
                color = {"pending": "yellow", "verified": "green",
                         "stale": "magenta", "suspect": "red"}[s]
                table.add_row(f"[{color}]● {s}[/{color}]", str(summary[s]))
            console.print(table)
            console.print("[dim]Hint: hfpclawer store conflicts — list cross-source identifier conflicts[/dim]")

    elif action == "conflicts":
        # Cross-source identifier conflicts (symbolic, 0-LLM)
        conflicts = store_obj.detect_identifier_conflicts(limit=50)
        if not conflicts:
            console.print("[green]✅ No identifier conflicts found[/green]")
        else:
            table = Table(title=f"⚠️ {len(conflicts)} identifier conflicts")
            table.add_column("sf_id", style="cyan")
            table.add_column("arxiv_id", style="white")
            table.add_column("DOI→arXiv", style="red")
            table.add_column("Title", style="dim")
            for c in conflicts:
                table.add_row(str(c["sf_id"]), c["arxiv_id"], c["doi_arxiv"], (c["title"] or "")[:50])
            console.print(table)
            console.print("[dim]Flag as suspect: hfpclawer store suspect <arxiv_id> \"<reason>\"[/dim]")

    elif action == "suspect":
        # Explicit abstain: flag a paper suspect with a reason
        if not arxiv_id:
            console.print("[red]❌ Requires --aid (arXiv ID); reason as ARG: hfpclawer store suspect --aid 2501.01934 \"<reason>\"[/red]")
            raise typer.Exit(1)
        reason = arg or "manual flag"
        paper = store_obj.get_paper_by_identifier("arxiv", arxiv_id)
        if not paper:
            console.print(f"[red]❌ {arxiv_id} not found[/red]")
            raise typer.Exit(1)
        store_obj.mark_suspect(paper.sf_id, reason)
        console.print(f"[red]⚠️ {arxiv_id} flagged suspect: {reason}[/red]")
        console.print("[dim]Adjudicate & clear: hfpclawer store clear-suspect --aid <arxiv_id>[/dim]")

    elif action == "clear-suspect":
        if not arxiv_id:
            console.print("[red]❌ Requires --aid: hfpclawer store clear-suspect --aid <arxiv_id>[/red]")
            raise typer.Exit(1)
        paper = store_obj.get_paper_by_identifier("arxiv", arxiv_id)
        if not paper:
            console.print(f"[red]❌ {arxiv_id} not found[/red]")
            raise typer.Exit(1)
        store_obj.clear_suspect(paper.sf_id)
        console.print(f"[green]✅ {arxiv_id} suspect flag cleared (audit_level unchanged)[/green]")

    else:
        console.print(f"[red]❌ Unknown action: {action}[/red]")


@app.command()
def rank(
    action: str = typer.Argument("train", help="train"),
    audit: str = typer.Option("", "--audit", help="Audit JSONL path from graph expand-hub --audit"),
    out_model: str = typer.Option("data/rank_model.txt", "--out", help="Output lightgbm model path"),
    n_estimators: int = typer.Option(200, "--n-estimators", help="Boosting rounds"),
):
    """Learned re-ranking (L1, opt-in): train lightgbm on hub-expansion audit trail.

    Positive = papers the hub heuristic adopted into the next frontier;
    negative = candidates truncated at the same layer. Tree feature
    importance = audit ("why was this ranked"). Requires hfpclawer[rank].
    """
    from hfpapers.rank import train as rank_train

    if action == "train":
        if not audit:
            console.print("[red]❌ Requires --audit <audit.jsonl> (from graph expand-hub --audit)[/red]")
            raise typer.Exit(1)
        try:
            res = rank_train(audit, out_model=out_model, n_estimators=n_estimators)
        except ImportError:
            console.print("[yellow]⚠️  lightgbm not installed — pip install hfpclawer[rank][/yellow]")
            raise typer.Exit(1)
        except ValueError as e:
            console.print(f"[red]❌ {e}[/red]")
            raise typer.Exit(1)
        console.print(f"[green]✅ Rank model trained: {res['rows']} audit rows[/green]")
        console.print(f"   positives={res['positives']}  negatives={res['negatives']}")
        importance = res["feature_importance"]
        top = sorted(importance.items(), key=lambda kv: -kv[1])
        console.print("   feature importance (audit):")
        for feat, imp in top:
            console.print(f"     {feat}: {imp:.1f}")
        if res.get("model_path"):
            console.print(f"   model: {res['model_path']}")
    else:
        console.print("[red]❌ Unknown action (only: train)[/red]")
        raise typer.Exit(1)


@app.command()
def ledger(
    action: str = typer.Argument("stats", help="log | list | stats"),
    event: str = typer.Option("manual", "--event", help="Event name (log)"),
    source: str = typer.Option("", "--source", help="Source tag (log)"),
    sf_delta: int = typer.Option(0, "--delta", help="sf_id delta (log)"),
    cost: float = typer.Option(0.0, "--cost", help="Real LLM cost USD from usage response (log)"),
    note: str = typer.Option("", "--note", help="next_hypothesis note (log)"),
    limit: int = typer.Option(20, "--limit", "-l", help="Rows to show (list)"),
    days: int = typer.Option(30, "--days", help="Stats window (stats)"),
):
    """Run-level accounting (HL-ledger style, append-only JSONL).

    llm_cost must come from a REAL usage response (L1 direct), never guessed;
    Hermes-attribution & balance reconciliation are tracked outside the repo.
    """
    from hfpapers.config import load_config, get
    from hfpapers.ledger import log as _log
    from hfpapers.ledger import recent, stats

    load_config()
    data_dir = get("paths.data_dir", "data")
    if action == "log":
        row = _log(data_dir, event=event, source=source, sf_id_delta=sf_delta,
                   llm_cost=cost, next_hypothesis=note)
        console.print(f"[green]✅ ledger row @ {row['timestamp']}[/green]")
        console.print(f"   event={row['event']}  source={row['source']}  "
                      f"sf_delta={row['sf_id_delta']}  cost=${row['llm_cost']}")
    elif action == "list":
        rows = recent(data_dir, limit=limit)
        if not rows:
            console.print("[yellow]Ledger empty[/yellow]")
            return
        table = Table(title=f"📒 Ledger (last {len(rows)})")
        table.add_column("Time", style="dim")
        table.add_column("Event", style="cyan")
        table.add_column("Source", style="white")
        table.add_column("Δsf", justify="right")
        table.add_column("$", justify="right")
        for r in rows:
            table.add_row(r.get("timestamp", "")[11:19], r.get("event", ""),
                          r.get("source", "")[:18], str(r.get("sf_id_delta", 0)),
                          f"{float(r.get('llm_cost', 0)):.4f}")
        console.print(table)
    elif action == "stats":
        st = stats(data_dir, since_days=days)
        console.print(f"[cyan]📊 Ledger stats (last {st['since_days']}d)[/cyan]")
        console.print(f"   rows: {st['rows']}   sf_id delta: +{st['sf_id_delta']}")
        console.print(f"   llm_cost total: ${st['llm_cost_total']}")
        for ev, c in sorted(st["by_event"].items(), key=lambda kv: -kv[1]):
            console.print(f"     {ev}: {c}")
    else:
        console.print("[red]❌ Unknown action (log | list | stats)[/red]")
        raise typer.Exit(1)


@app.command()
def check_new(
    since_minutes: int = typer.Option(0, "--since", help="Reserved window (0 = any change since last check)"),
):
    """0-token store change detection for cron monitor gate.

    Output is IDENTICAL when nothing changed → safe to use as a Hermes cron
    monitor: unchanged output skips the LLM entirely (0-token operation).
    """
    from hfpapers.config import load_config, get
    from hfpapers.ledger import check_new as _check
    from hfpapers.paper_store import get_store

    load_config()
    data_dir = get("paths.data_dir", "data")
    result = _check(get_store(), data_dir, since_minutes=since_minutes)
    if result["new_papers"] == 0:
        console.print(f"NO_CHANGE total={result['total']} "
                      f"(prev {result['prev_total']} @ {result['prev_checked_at'][:19]})")
    else:
        console.print(f"CHANGE +{result['new_papers']} new papers "
                      f"(total {result['total']}, first_new_sf={result['first_new_id']})")


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


@app.command(name="download-meta")
def download_meta(  # noqa: F811 — renamed from `download` to avoid redefinition
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


@app.command()
def import_cmd(
    identifier: str = typer.Argument(..., help="arXiv ID (2501.01934), DOI (10.1016/...), or URL"),
    title: str = typer.Option("", "--title", "-t", help="Paper title (optional)"),
    abstract: str = typer.Option("", "--abstract", "-a", help="Paper abstract (optional)"),
    venue: str = typer.Option("", "--venue", "-v", help="Venue (optional)"),
    source: str = typer.Option("import", "--source", help="Source label for the paper record"),
    skip_pdf: bool = typer.Option(False, "--skip-pdf", help="Skip PDF download"),
    skip_md: bool = typer.Option(False, "--skip-md", help="Skip PDF→MD conversion"),
    verbose: bool = typer.Option(False, "--verbose", help="Verbose step logging"),
):
    """Import a paper by arXiv ID / DOI / URL (atomic pipeline).

    Resolves the identifier → dedup check → PDF download (3-level fallback)
    → pymupdf4llm conversion → PaperStore write.

    Examples:

        hfpclawer import 2501.01934

        hfpclawer import 10.1016/j.jcp.2025.114432 --skip-pdf

        hfpclawer import https://arxiv.org/abs/2501.01934 --title "Fusion DeepONet"
    """
    from hfpclawer.import_paper.importer import import_arxiv_id

    with console.status(f"[dim]Importing {identifier}...[/dim]"):
        result = import_arxiv_id(
            raw_id=identifier,
            title=title,
            abstract=abstract,
            venue=venue,
            source=source,
            download_pdf=not skip_pdf,
            convert_md=not skip_md,
            verbose=verbose,
        )

    if result.ok:
        console.print("[bold green]✅ Imported[/bold green]")
        console.print(f"  sf_id: [cyan]{result.sf_id}[/cyan]")
        if result.pdf_path:
            console.print(f"  PDF:   [dim]{result.pdf_path}[/dim]")
        if result.md_path:
            console.print(f"  MD:    [dim]{result.md_path}[/dim]")
        if verbose and result.steps:
            console.print(f"  Steps: {', '.join(result.steps)}")
        # Run-level accounting (ledger): real import = +1 sf_id, 0-token append
        try:
            from hfpapers.config import get as cfg_get
            from hfpapers.ledger import log as ledger_log

            ledger_log(cfg_get("paths.data_dir", "data"), event="import",
                       source="cli", sf_id_delta=1)
        except Exception:
            pass  # ledger is best-effort; import success must not depend on it
    elif result.status == "duplicate":
        console.print("[yellow]⏭️  Already in store[/yellow]")
        console.print(f"  sf_id: [cyan]{result.sf_id}[/cyan]")
    else:
        console.print(f"[red]❌ Import failed: {result.error}[/red]")
        if verbose and result.steps:
            console.print(f"  Steps: {', '.join(result.steps)}")
        raise typer.Exit(1)


@app.command()
def semantic_service(
    host: str = typer.Option("127.0.0.1", "--host", "-h", help="Bind address"),
    port: int = typer.Option(8765, "--port", "-p", help="Port"),
    preload: bool = typer.Option(False, "--preload", help="Preload model on startup"),
    log_level: str = typer.Option(
        "info", "--log-level", help="Logging level: debug, info, warning, error"
    ),
):
    """Start the semantic similarity sidecar (FastAPI + sentence-transformers).

    Provides /embed, /similarity, /classify endpoints for expflow.

    Requires: pip install sentence-transformers
    Model: all-MiniLM-L6-v2 (~80MB, CPU/GPU)
    """
    import sys

    from hfpapers.semantic_service import main

    sys.argv = [
        "semantic-service",
        "--host",
        host,
        "--port",
        str(port),
        "--log-level",
        log_level,
    ]
    if preload:
        sys.argv.append("--preload")
    main()


# ════════════════════════════════════════════════════════
# Source Commands — Multi-source document adapters
# ════════════════════════════════════════════════════════


@app.command()
def source_list():
    """List all available document source adapters"""
    from hfpapers.source_adapters import list_sources

    names = list_sources()
    if not names:
        typer.echo("No source adapters registered.")
        raise typer.Exit(0)
    typer.echo("Available sources:")
    for name in names:
        typer.echo(f"  · {name}")


@app.command()
def source_fetch(
    source: str = typer.Argument(..., help="Source name (e.g. gh_ingest)"),
    doc_id: str = typer.Argument(..., help="Document ID to fetch"),
):
    """Fetch a document from a source by its ID

    Example: hfpclawer source fetch gh_ingest owner/repo
    """
    from hfpapers.source_adapters import get_source

    s = get_source(source)
    if s is None:
        typer.echo(
            f"Unknown source '{source}'. Use `hfpclawer source-list` to see available sources.",
            err=True,
        )
        raise typer.Exit(1)
    doc = s.fetch(doc_id)
    if doc is None:
        typer.echo(f"Document '{doc_id}' not found in '{source}'.", err=True)
        raise typer.Exit(1)
    typer.echo(f"Title:    {doc.title}")
    typer.echo(f"Source:   {doc.source}")
    typer.echo(f"URL:      {doc.source_url}")
    typer.echo(f"Code:     {doc.code_url}")
    typer.echo(f"Abstract: {doc.abstract[:200]}...")
    if doc.tags:
        typer.echo(f"Tags:     {', '.join(doc.tags)}")


@app.command()
def source_search(
    source: str = typer.Argument(..., help="Source name"),
    query: str = typer.Argument(..., help="Search query"),
    limit: int = typer.Option(10, "--limit", "-l", help="Max results"),
):
    """Search a source for documents matching query"""
    from hfpapers.source_adapters import get_source

    s = get_source(source)
    if s is None:
        typer.echo(f"Unknown source '{source}'.", err=True)
        raise typer.Exit(1)
    docs = s.search(query, limit=limit)
    if not docs:
        typer.echo(f"No results for '{query}' in '{source}'.")
        raise typer.Exit(0)
    typer.echo(f"Found {len(docs)} result(s):")
    for i, doc in enumerate(docs, 1):
        typer.echo(f"  {i}. [{doc.id}] {doc.title}")


@app.command()
def source_ingest(
    source: str = typer.Argument(..., help="Source name"),
    doc_id: str = typer.Argument(..., help="Document ID to ingest to paper_store"),
):
    """Ingest a source document into paper_store

    Example: hfpclawer source ingest gh_ingest owner/repo
    """
    from hfpapers.source_adapters import get_source

    s = get_source(source)
    if s is None:
        typer.echo(f"Unknown source '{source}'.", err=True)
        raise typer.Exit(1)
    doc = s.fetch(doc_id)
    if doc is None:
        typer.echo(f"Document '{doc_id}' not found.", err=True)
        raise typer.Exit(1)
    sf_id, is_new = s.ingest_to_paper_store(doc)
    typer.echo(f"{'✅' if is_new else '🔁'} {doc.title} → paper_store (id={sf_id}, new={is_new})")
