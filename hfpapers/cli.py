# ─── CLI 入口 ──────────────────────────────
# cli.py — typer CLI for Hermes & OpenCode
# v3.3: 集成 SearchDispatcher 异步搜索 + tqdm 进度显示

"""
用法:
  hfpclawer search           搜索+分类+列出新论文（异步多源搜索）
  hfpclawer download         下载 TOP 候选论文 PDF（8 并发）
  hfpclawer convert          pymupdf4llm 转 Markdown
  hfpclawer full             全流程 pipeline（search → download → convert）
  hfpclawer dedup            去重状态
  hfpclawer list|ls          列出所有论文
  hfpclawer info <arxiv_id>  查单篇论文详情
  hfpclawer sniff            LLM 驱动的纸议分析（分析新论文摘要）
  hfpclawer analyze          LLM 分析已下载 PDF
  hfpclawer wiki             生成 Wiki 页面
  hfpclawer store            论文存储层管理
  hfpclawer audit            数据源审计报告
  hfpclawer check            检查最新 paper
  hfpclawer config           查看当前配置
  hfpclawer mcp              启动 MCP Server
  hfpclawer stats            搜索统计
"""

import json
import logging
import time
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table
from rich.progress import (
    Progress, SpinnerColumn, TextColumn, BarColumn,
    TaskProgressColumn, TimeRemainingColumn,
)

from hfpapers.config import load_config, get
from hfpapers.hardware import HardwareProbe

app = typer.Typer(name="hfpclawer", help="HF Papers 爬虫 + Wiki 集成")
logger = logging.getLogger("hfpclawer")
console = Console()


@app.callback()
def main_callback(verbose: bool = typer.Option(False, "--verbose", "-v")):
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )


def _get_probe() -> HardwareProbe:
    return HardwareProbe()


# ════════════════════════════════════════════
# 子命令
# ════════════════════════════════════════════


@app.command()
def search(
    max_pages: int = typer.Option(3, "--max-pages", "-p", help="每维度页数"),
    threshold: int = typer.Option(30, "--threshold", "-t", help="相关度阈值"),
    dry_run: bool = typer.Option(False, "--dry-run", "-n", help="仅搜索+显示，不保存"),
    show_all: bool = typer.Option(False, "--all", "-a", help="显示所有结果（含低相关度）"),
):
    """搜索 HF Papers → arXiv验证 → 分类

    使用 SearchDispatcher 异步多源并发搜索（HF CLI, arXiv本地/API, OpenReview）。
    """
    from hfpapers.evolved import HFPapersCrawler, DedupEngine, RelevanceDetector, PaperInfo
    from hfpapers.config import load_config

    hw = _get_probe()
    console.print(f"[dim]🔧 {hw.summary()}[/dim]")

    dedup = DedupEngine()
    detector = RelevanceDetector()
    clawler = HFPapersCrawler(dedup=dedup, detector=detector)

    start_t = time.time()
    papers = clawler.crawl(max_pages=max_pages)
    elapsed = time.time() - start_t

    if not show_all:
        papers = [p for p in papers if p.relevance >= threshold]

    # 分类统计
    by_cat: dict[str, list] = {}
    for p in papers:
        cat = p.categories[0] if p.categories else "unknown"
        by_cat.setdefault(cat, []).append(p)

    # Rich table
    table = Table(title=f"📄 新论文 ({len(papers)} 篇 in {elapsed:.1f}s)")
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
        console.print(f"[green]💾 候选列表: {path}[/green]")


@app.command()
def download(
    limit: int = typer.Option(20, "--limit", "-l", help="最多下载篇数"),
):
    """下载候选论文 PDF

    使用 AsyncPdfDownloader 8 并发下载，自动转 Markdown。
    """
    from hfpapers.evolved import PaperDownloader, DedupEngine, load_candidates

    dedup = DedupEngine()
    downloader = PaperDownloader(dedup=dedup)
    candidates = load_candidates()
    if not candidates:
        console.print("[red]❌ 没有候选列表，先运行 hfpclawer search[/red]")
        raise typer.Exit(1)

    papers = candidates[:limit]
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        TimeRemainingColumn(),
    ) as progress:
        task = progress.add_task(f"📥 下载 {len(papers)} 篇 PDF...", total=len(papers))
        downloader.download_batch(papers)
        progress.update(task, completed=len(papers))
    console.print("[green]✅ 下载完成[/green]")


@app.command()
def convert():
    """pymupdf4llm 转换 PDF → Markdown"""
    hw = _get_probe()
    if not hw.use_pdf_converter:
        console.print("[yellow]⚠️  pymupdf4llm 不可用，跳过转换[/yellow]")
        raise typer.Exit(0)

    from hfpapers.evolved import convert_pdfs
    count = convert_pdfs()
    console.print(f"[green]✅ 转换 {count} 篇[/green]")


@app.command()
def full(
    max_pages: int = typer.Option(3, "--max-pages", "-p", help="每维度页数"),
    threshold: int = typer.Option(30, "--threshold", "-t", help="相关度阈值"),
    limit: int = typer.Option(20, "--limit", "-l", help="下载上限"),
    skip_convert: bool = typer.Option(False, "--skip-convert", help="跳过 PDF→MD 转换"),
):
    """全流程: search → download → convert

    使用 SearchDispatcher 异步搜索 + AsyncPdfDownloader 并发下载。
    """
    from hfpapers.evolved import HFPapersCrawler, DedupEngine, RelevanceDetector
    HFPapersCrawler  # 触发导入

    start_t = time.time()

    # Step 1: Search
    console.rule("[bold cyan]Step 1/3: 搜索 arXiv 论文[/bold cyan]")
    search(max_pages=max_pages, threshold=threshold, dry_run=False)

    candidates_path = Path(get("paths.data_dir", "data")).expanduser() / "candidates_latest.json"
    if not candidates_path.exists():
        console.print("[red]❌ 搜索未产生候选论文，终止[/red]")
        raise typer.Exit(0)

    # Step 2: Download
    if limit > 0:
        console.rule("[bold cyan]Step 2/3: 下载 PDF[/bold cyan]")
        download(limit=limit)

    # Step 3: Convert
    if not skip_convert:
        hw = _get_probe()
        if hw.use_pdf_converter:
            console.rule("[bold cyan]Step 3/3: PDF → Markdown[/bold cyan]")
            convert()
        else:
            console.print("[yellow]⚠️  跳过转换（pymupdf4llm 不可用）[/yellow]")

    total_elapsed = time.time() - start_t
    console.print(f"\n[bold green]✅ 全流程完成 ({total_elapsed:.0f}s)[/bold green]")


@app.command()
def dedup():
    """查看去重统计"""
    from hfpapers.evolved import DedupEngine
    d = DedupEngine()
    pdf_dir = Path(get("paths.pdf_dir", "pdfs")).expanduser()
    md_dir = Path(get("paths.md_dir", "mds")).expanduser()

    stats = Table(title="📊 去重统计")
    stats.add_column("指标", style="cyan")
    stats.add_column("数值", style="white")
    stats.add_row("去重记录", str(d.count))
    stats.add_row("PDF 文件数", str(len(list(pdf_dir.glob("*.pdf")))))
    stats.add_row("MD 文件数", str(len(list(md_dir.glob("*.md")))))
    console.print(stats)


@app.command(name="list")
def list_papers(
    limit: int = typer.Option(20, "--limit", "-l", help="显示条数"),
    category: Optional[str] = typer.Option(None, "--category", "-c", help="分类过滤"),
):
    """列出已爬取论文"""
    import json
    dedup_path = Path(get("paths.global_dedup")).expanduser()
    if not dedup_path.exists():
        console.print("[red]❌ 去重文件不存在[/red]")
        raise typer.Exit(1)

    with open(dedup_path) as f:
        data = json.load(f)
    papers = data.get("papers", {})

    table = Table(title=f"📚 论文 ({len(papers)} 篇)")
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
        console.print("[yellow]没有匹配的论文[/yellow]")


@app.command()
def info(arxiv_id: str):
    """查单篇论文"""
    import json
    dedup_path = Path(get("paths.global_dedup")).expanduser()
    with open(dedup_path) as f:
        data = json.load(f)
    p = data.get("papers", {}).get(arxiv_id)
    if not p:
        console.print(f"[red]❌ {arxiv_id} 未找到[/red]")
        raise typer.Exit(1)
    console.print_json(data=p)


@app.command()
def stats():
    """搜索统计 — SearchQueue 任务完成情况"""
    from hfpapers.evolved import DedupEngine
    d = DedupEngine()
    hw = _get_probe()
    store_stats = {}
    try:
        from hfpapers.paper_store import store_stats as ss
        store_stats = ss()
    except Exception:
        pass

    table = Table(title="📊 系统统计")
    table.add_column("指标", style="cyan")
    table.add_column("数值", style="white")
    table.add_row("去重记录", str(d.count))
    table.add_row("搜索查询数", str(len(get("search.queries", []))))
    table.add_row("Paper Store 论文", str(store_stats.get("papers_total", "N/A")))
    table.add_row("Paper Store 已验证", str(store_stats.get("papers_verified", "N/A")))
    for k, v in hw.__dict__.items():
        table.add_row(f"HW.{k}", str(v))
    console.print(table)


@app.command()
def config():
    """查看当前配置"""
    cfg = load_config()
    console.print_json(data=cfg)


@app.command()
def store(
    action: str = typer.Argument("stats", help="stats | ensure | search | export | verify | ids"),
    arg: str = typer.Argument("", help="参数: keyword(for search) / format(for export)"),
    arxiv_id: str = typer.Option("", "--aid", "-a", help="arXiv ID"),
    title: str = typer.Option("", "--title", "-t", help="论文标题"),
    keyword: str = typer.Option("", "--keyword", "-k", help="搜索关键词"),
    limit: int = typer.Option(20, "--limit", "-l", help="结果条数"),
):
    """论文存储层管理 (SQLite + 雪花ID + Crossref)"""
    from hfpapers.paper_store import get_store, get_crossref, ensure_paper, store_stats

    store_obj = get_store()

    if action == "stats":
        ss = store_stats()
        table = Table(title="📊 Paper Store 统计")
        table.add_column("指标", style="cyan")
        table.add_column("数值", style="white")
        table.add_row("论文总数", str(ss["papers_total"]))
        table.add_row("已验证", str(ss["papers_verified"]))
        table.add_row("有代码", str(ss["papers_with_code"]))
        table.add_row("标识符总数", str(ss["identifiers_total"]))
        for t, c in ss["identifiers_by_type"].items():
            table.add_row(f"  标识符: {t}", str(c))
        console.print(table)

    elif action == "ensure":
        if not arxiv_id:
            console.print("[red]❌ 需要 --aid[/red]")
            raise typer.Exit(1)
        sf_id, is_new = ensure_paper(arxiv_id, title=title, source="cli")
        paper = store_obj.get_paper_by_id(sf_id)
        ids = store_obj.get_identifiers(sf_id)
        console.print(f"{'🆕 新建' if is_new else '✅ 已有'}: sf_id={sf_id}")
        console.print(f"  标题: {paper.title}")
        console.print(f"  验证: {'✅' if paper.verified else '❌'}")
        for i in ids:
            console.print(f"  {i.id_type}: {i.id_value} (conf={i.confidence})")

    elif action == "search":
        papers = store_obj.search_papers(keyword or arg, limit=limit)
        table = Table(title=f"📚 找到 {len(papers)} 篇论文")
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
            console.print("[red]❌ 需要 --aid[/red]")
            raise typer.Exit(1)
        cr = get_crossref()
        result = cr.cross_verify(arxiv_id, title if title else arxiv_id)
        if result:
            console.print("[green]✅ 交叉验证成功:[/green]")
            for k, v in result.items():
                console.print(f"  {k}: {v}")
        else:
            console.print("[yellow]❌ 未找到匹配[/yellow]")

    elif action == "ids":
        if not arxiv_id:
            console.print("[red]❌ 需要 --aid[/red]")
            raise typer.Exit(1)
        paper = store_obj.get_paper_by_identifier("arxiv", arxiv_id)
        if paper:
            ids_list = store_obj.get_identifiers(paper.sf_id)
            console.print(f"论文: {paper.title}")
            for i in ids_list:
                console.print(f"  {i.id_type}: {i.id_value}")
        else:
            console.print(f"[red]❌ {arxiv_id} 未找到[/red]")

    elif action == "export":
        fmt = arg or "json"
        if fmt not in ("json", "csv"):
            console.print(f"[red]❌ 不支持格式: {fmt} (仅 json/csv)[/red]")
            raise typer.Exit(1)
        try:
            out_path = store_obj.export_papers(format=fmt)
            console.print(f"[green]✅ 已导出 {store_obj.stats()['papers_total']} 篇论文[/green]")
            console.print(f"[dim]   {out_path}[/dim]")
        except ValueError as e:
            console.print(f"[yellow]{e}[/yellow]")
            raise typer.Exit(0)

    else:
        console.print(f"[red]❌ 未知操作: {action}[/red]")


@app.command()
def sniff(
    max_papers: int = typer.Option(10, "--max-papers", "-n", help="最多分析论文数"),
    threshold: int = typer.Option(30, "--threshold", "-t", help="相关度阈值"),
):
    """LLM 分析候选论文摘要

    从最新候选列表中取论文，用 LLM 分析它们的摘要：
    - 核心贡献（中文概述）
    - 技术方法
    - 与已有工作的区别
    - 是否值得深入阅读
    """
    from hfpapers.evolved import load_candidates
    from hfpapers.config import get as cfg_get

    candidates = load_candidates()
    if not candidates:
        console.print("[red]❌ 没有候选列表，先运行 hfpclawer search[/red]")
        raise typer.Exit(1)

    papers = [p for p in candidates if p.relevance >= threshold][:max_papers]
    if not papers:
        console.print(f"[yellow]没有相关度 ≥ {threshold} 的论文[/yellow]")
        raise typer.Exit(0)

    console.print(f"[bold cyan]🔍 分析 {len(papers)} 篇论文摘要...[/bold cyan]")

    # 提取摘要文本
    summaries = []
    for p in papers:
        summary = p.abstract.strip() if p.abstract else ""
        if not summary:
            # 尝试从 arXiv 拉取
            import requests
            try:
                from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning
                import warnings
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

        summaries.append({
            "arxiv_id": p.arxiv_id,
            "title": p.title,
            "relevance": p.relevance,
            "abstract": summary[:1000] if summary else "(无摘要)",
        })

    # 构造 LLM prompt
    prompt_sections = []
    for s in summaries:
        prompt_sections.append(
            f"## {s['arxiv_id']} — {s['title']} (rel={s['relevance']})\n\n"
            f"摘要: {s['abstract']}\n"
        )

    prompt = (
        "你是一个专注 AI4S 的研究助理，分析以下论文摘要。对每篇论文输出:\n"
        "  1. **核心贡献**（1-2句话，中文）\n"
        "  2. **技术方法**（关键词）\n"
        "  3. **值得阅读?** ⭐1-5星\n"
        "  4. **推荐理由**（一句话）\n\n"
        f"共 {len(prompt_sections)} 篇论文:\n\n"
        + "\n---\n".join(prompt_sections)
    )

    # 调用 LLM
    try:
        from litellm import completion
        model = cfg_get("llm.sniff_model", "deepseek/deepseek-chat")
        max_tokens = cfg_get("llm.sniff_max_tokens", 2000)

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
        ) as progress:
            progress.add_task(f"🤖 调用 {model} 分析摘要...", total=None)
            resp = completion(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=max_tokens,
                temperature=0.3,
            )

        analysis = resp.choices[0].message.content
        console.print("\n[bold]📋 LLM 分析结果:[/bold]")
        console.print(analysis)

        # 保存到文件
        from datetime import datetime
        now = datetime.now().strftime("%Y%m%d_%H%M%S")
        data_dir = Path(cfg_get("paths.data_dir", "data")).expanduser()
        out_path = data_dir / f"sniff_{now}.md"
        with open(out_path, "w") as f:
            f.write(f"# LLM 论文分析 ({now})\n\n")
            f.write(f"来源: candidates_latest.json (rel≥{threshold}, top {len(papers)})\n\n")
            f.write(analysis)
        console.print(f"[dim]💾 分析已保存: {out_path}[/dim]")

    except Exception as e:
        console.print(f"[red]❌ LLM 调用失败: {e}[/red]")
        console.print("\n[yellow]改用本地关键词摘要模式:[/yellow]")

        # fallback: 关键词提取
        for s in summaries:
            kw = _extract_keywords(s["abstract"])
            console.print(f"\n[bold]{s['arxiv_id']}[/bold] {s['title'][:60]}")
            console.print(f"  关键词: {', '.join(kw[:10])}")
            console.print(f"  相关度: {s['relevance']}")


def _extract_keywords(text: str, max_kw: int = 15) -> list[str]:
    """简单关键词提取（fallback，LLM 不可用时）"""
    import re
    # 取专业术语（大写首字母词、有连字符的技术名词）
    patterns = [
        r"[A-Z][a-z]+(?:[-/][A-Z][a-z]+)*",  # Neural Operator, Physics-Informed
        r"\b(?:PDE|FNO|DeepONet|PINN|GAN|Transformer|CNN|RNN|MLP|ViT|INR|SOTA)\b",
    ]
    words = set()
    text_lower = text.lower()
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
    """启动 MCP Server（Hermes / OpenCode 集成）

    stdio 模式（默认）：用于 Hermes Agent 原生 MCP 客户端。
    http 模式：用于 OpenCode subagent 或调试。
    """
    from hfpapers.mcp_server import run_mcp_server
    if mode == "http":
        console.print(f"🚀 MCP Server → http://{host}:{port}")
    run_mcp_server(host=host, port=port, mode=mode)


# ════════════════════════════════════════════
# 下载子命令 — hfpclawer/download 管道
# ════════════════════════════════════════════


@app.command()
def download(
    source: str = typer.Option("oai", "--source", "-s",
                               help="数据源: oai（OAI-PMH增量）| kaggle（Kaggle全量）"),
    incremental: bool = typer.Option(False, "--incremental", "-i",
                                     help="OAI 增量模式（仅最近1天）"),
    all_papers: bool = typer.Option(False, "--all", "-a",
                                    help="OAI 全量拉取（按优先级全部下载）"),
    tier1: bool = typer.Option(False, "--tier1", "-t1",
                               help="OAI 仅下载 Tier 1 核心分类"),
    force: bool = typer.Option(False, "--force", "-f",
                               help="Kaggle 强制重新下载"),
    status: bool = typer.Option(False, "--status",
                                help="查看下载进度"),
):
    """下载 arXiv 元数据（OAI-PMH 增量|全量 / Kaggle 全量）"""
    from hfpclawer.download.base import ResumeState
    from hfpapers.config import get as cfg_get

    if status:
        # 查看状态
        db_path = str(Path(__file__).resolve().parent.parent / cfg_get("db.path", "data/arxiv_meta.db"))
        state = ResumeState(db_path, source).get()
        console.print(f"\n📊 [{source}] 下载状态")
        console.print(f"  状态:        {state.get('status', 'unknown')}")
        console.print(f"  已获取:      {state.get('total_fetched', 0):,}")
        console.print(f"  新增:        {state.get('total_new', 0):,}")
        console.print(f"  上次更新:    {state.get('last_update', '从未')}")
        console.print(f"  checksum:    {state.get('checksum', 'N/A')}")
        return

    if source == "oai":
        from hfpclawer.download.oai import OaiPmhDownloader
        dl = OaiPmhDownloader()
        with console.status("[bold cyan]📥 下载 arXiv OAI-PMH 元数据..."):
            total = dl.run(
                incremental=incremental,
                from_date="",
                tier1_only=tier1,
            )
        console.print(f"[green]✅ 下载完成: +{total:,} 篇[/green]")

    elif source == "kaggle":
        from hfpclawer.download.kaggle import KaggleDownloader
        dl = KaggleDownloader()
        with console.status("[bold cyan]📥 从 Kaggle 下载 arXiv 元数据集..."):
            total = dl.run(force=force)
        if total > 0:
            console.print(f"[green]✅ Kaggle 下载完成: {total:,} 篇[/green]")
        else:
            console.print("[green]✅ 数据集已是最新，无需下载[/green]")

    else:
        console.print(f"[red]❌ 未知数据源: {source} (可选: oai, kaggle)[/red]")


@app.command()
def audit(
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON 格式输出"),
):
    """数据源审计报告 — 查看各来源论文数、状态文件、JSONL 状态"""
    from hfpclawer.audit import run_audit, format_audit_report

    report = run_audit()
    if json_output:
        import json as json_mod
        console.print(json_mod.dumps(report, indent=2, ensure_ascii=False))
    else:
        console.print(format_audit_report(report))


def _import_dummy():
    """确保 import 加载"""
    pass


@app.command()
def monitor(
    action: str = typer.Argument("status",
                                 help="start | stop | status"),
    interval: int = typer.Option(900, "--interval", "-i",
                                 help="轮询间隔（秒，默认 900=15分钟）"),
):
    """后台监控守护 — 定时轮询 OAI-PMH 增量下载"""
    from hfpclawer.download.monitor import MonitorDaemon
    from hfpapers.config import load_config

    cfg = load_config()
    base_dir = Path(__file__).resolve().parent.parent
    daemon = MonitorDaemon(base_dir=str(base_dir), interval=interval)

    if action == "start":
        if daemon.start():
            console.print(f"[green]✅ MonitorDaemon 已启动 (PID={daemon._read_pid()})[/green]")
            console.print(f"[dim]   日志: {daemon.log_path}[/dim]")
        else:
            console.print(f"[yellow]⚠️  MonitorDaemon 已在运行[/yellow]")

    elif action == "stop":
        if daemon.stop():
            console.print(f"[green]✅ MonitorDaemon 已停止[/green]")
        else:
            console.print(f"[yellow]⚠️  MonitorDaemon 未运行[/yellow]")

    elif action == "status":
        st = daemon.status()
        if st["running"]:
            console.print(f"[green]✅ MonitorDaemon 运行中[/green]")
            console.print(f"  PID:      {st['pid']}")
            console.print(f"  间隔:     {st['interval']}s")
            ds = st.get("download_state", {})
            if ds and "error" not in ds:
                console.print(f"  下载状态: {ds.get('status', 'N/A')}")
                console.print(f"  DB论文数: {ds.get('total_new', 0):,}")
        else:
            console.print(f"[yellow]⚠️  MonitorDaemon 未运行[/yellow]")
        console.print(f"  PID 文件: {st['pid_file']}")
        console.print(f"  日志文件: {st['log_file']}")
