#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
verify_cli.py — hfpclawer verify CLI subcommand.

Usage:
    hfpclawer verify list                         # Registry statistics
    hfpclawer verify stats                        # Detailed registry stats
    hfpclawer verify add <fid> "<latex>"          # Add formula to registry
    hfpclawer verify run                          # Run all unverified
    hfpclawer verify fid <fid>                    # Verify one formula
    hfpclawer verify check "<latex>"              # Ad-hoc: check LaTeX syntax
    hfpclawer verify cross <fid>                  # Run CAS cross-validation only
"""

from __future__ import annotations

import typer
from rich.console import Console
from rich.table import Table

verify_app = typer.Typer(name="verify", help="Formula verification & CAS cross-validation")

# ── Report generators ────────────────────────


def _generate_latex_report(
    entry: "FormulaEntry",
    results: list["LayerResult"],
) -> str:
    """Generate a LaTeX snippet report for a verified formula."""
    lines = []

    # Build status summary
    total = len(results)
    passed = sum(1 for r in results if r.passed)
    reliability = "A" if passed == total else "B" if passed >= total - 1 else "C"

    # Section header
    lines.append(r"\section{验证报告 — Verification Report}")
    lines.append(r"\label{sec:verify-" + entry.fid.replace(":", "-") + "}")
    lines.append("")

    # Basic info table
    lines.append(r"\subsection{基本信息 — Basic Information}")
    lines.append(r"\begin{tabular}{ll}")
    lines.append(r"\toprule")
    lines.append(r"字段 & 值 \\")
    lines.append(r"\midrule")
    lines.append(f"FID & \\texttt{{{entry.fid}}} \\\\")
    lines.append(f"LaTeX & ${entry.latex}$ \\\\")
    lines.append(f"维数 & {entry.pint_dimension or '---'} \\\\")
    lines.append(f"来源 & {', '.join(entry.source_keys) if entry.source_keys else '---'} \\\\")
    lines.append(f"标签 & {', '.join(entry.tags) if entry.tags else '---'} \\\\")
    lines.append(f"可信度 & {reliability}（{passed}/{total} 通过）\\\\")
    lines.append(r"\bottomrule")
    lines.append(r"\end{tabular}")
    lines.append("")

    # Layer-by-layer results
    lines.append(r"\subsection{验证流水线 — Verification Pipeline}")
    for r in results:
        icon = r"$\checkmark$" if r.passed else r"$\times$"
        lines.append(f"\\paragraph{{{r.layer}}}: {icon} \\hfill {r.detail}")
        if r.cas and r.cas.proof_method:
            lines.append(f"CAS对比: {r.cas.engine_a} $\\leftrightarrow$ {r.cas.engine_b or '---'}, "
                         f"等价={r.cas.equivalent}, 策略={r.cas.proof_method}")
        lines.append("")

    # CAS equivalence proof detail
    cas_results = [r for r in results if r.cas and r.cas.proof_method]
    if cas_results:
        lines.append(r"\subsection{CAS等价性证明 — CAS Equivalence Proof}")
        for cr in cas_results:
            cas = cr.cas
            lines.append(f"\\paragraph{{{cr.fid}}}")
            lines.append(r"\begin{align*}")
            lines.append(f"\\text{{SymPy}} &= {cas.sympy_result} \\\\")
            lines.append(f"\\text{{Wolfram}} &= {cas.wolfram_result} \\\\")
            if cas.diff:
                lines.append(f"\\Delta &= {cas.diff}")
            lines.append(r"\end{align*}")
            lines.append(f"证明策略: \\texttt{{{cas.proof_method}}} --- {cas.detail}")
            lines.append("")

    # Numeric check details
    numeric_results = [r for r in results if r.computed is not None]
    if numeric_results:
        lines.append(r"\subsection{数值验证 — Numerical Verification}")
        lines.append(r"\begin{tabular}{lrrl}")
        lines.append(r"\toprule")
        lines.append(r"FID & 计算值 & 期望值 & 相对误差 \\")
        lines.append(r"\midrule")
        for nr in numeric_results:
            icon = r"$\checkmark$" if nr.passed else r"$\times$"
            lines.append(
                f"{icon} {nr.fid} & {nr.computed:.6e} & {nr.expected:.6e} & {nr.rel_error:.2e} \\\\"
            )
        lines.append(r"\bottomrule")
        lines.append(r"\end{tabular}")
        lines.append("")

    # Footer
    lines.append(r"\subsection{发表建议 — Publication Recommendation}")
    if passed == total:
        lines.append("所有验证层通过，建议发表等级：\\textbf{A}（双CAS独立验证 + 数值 + 量纲 + 极限）。")
    elif passed >= total - 1:
        lines.append(
            "大部分验证通过，建议发表等级：\\textbf{B}。推荐审查以下非通过层后再发表。"
        )
    else:
        lines.append(
            "多项验证未通过，建议发表等级：\\textbf{C}。请逐层排查后重新验证。"
        )
    lines.append("")

    return "\n".join(lines)


def _generate_qmd_report(
    entry: "FormulaEntry",
    results: list["LayerResult"],
    title: str = "",
) -> str:
    """Generate a full Quarto .qmd document from verification results."""
    doc_title = title or f"验证报告: {entry.fid} --- Formula Verification Report"

    lines = []
    # YAML frontmatter
    lines.append("---")
    lines.append(f'title: "{doc_title}"')
    lines.append('author: "hfpclawer verify report"')
    lines.append("lang: zh-CN")
    lines.append("format:")
    lines.append("  pdf:")
    lines.append("    documentclass: ctexart")
    lines.append("    fontsize: 11pt")
    lines.append("    geometry:")
    lines.append("      - margin=2.5cm")
    lines.append('    mainfont: "Liberation Serif"')
    lines.append("    header-includes: |")
    lines.append("      \\usepackage{booktabs}")
    lines.append("      \\usepackage{fancyhdr}")
    lines.append("      \\usepackage{amsmath,amssymb}")
    lines.append("      \\pagestyle{fancy}")
    lines.append("      \\fancyhf{}")
    lines.append("      \\rhead{\\thepage}")
    lines.append("      \\setlength{\\headheight}{14pt}")
    lines.append("    toc: false")
    lines.append("    number-sections: true")
    lines.append("---")
    lines.append("")

    # Generate the LaTeX body as a {=latex} block
    latex_body = _generate_latex_report(entry, results)
    lines.append("```{=latex}")
    lines.append(latex_body)
    lines.append("```")

    return "\n".join(lines)


console = Console()


# ── Helpers ────────────────────────────────────────

def _get_registry(path: str | None = None) -> "FormulaRegistry":
    """Load FormulaRegistry from default or specified path."""
    from hfpclawer.verify.registry import FormulaRegistry

    path = path or "formula_registry.jsonl"
    return FormulaRegistry(path=path)


def _get_pipeline(path: str | None = None, wolfram: bool = True):
    """Create a VerificationPipeline with settings."""
    from hfpclawer.verify.pipeline import VerificationPipeline

    reg = _get_registry(path)
    return VerificationPipeline(registry=reg, wolfram_enabled=wolfram)


# ── Commands ───────────────────────────────────────


@verify_app.command("list")
def list_cmd(
    registry_path: str = typer.Option(
        "formula_registry.jsonl", "--registry", "-r",
        help="Path to formula registry JSONL",
    ),
    status: str = typer.Option(
        "", "--status", "-s", help="Filter by status (verified|failed|unverified)",
    ),
):
    """List formulas in the registry."""
    reg = _get_registry(registry_path)
    entries = reg.load_all()

    if not entries:
        console.print("[yellow]Registry is empty.[/yellow]")
        raise typer.Exit(0)

    if status:
        entries = [e for e in entries if e.verification_status == status]

    table = Table(title=f"Formula Registry ({len(entries)} entries)")
    table.add_column("FID", style="cyan")
    table.add_column("LaTeX", style="white", max_width=50)
    table.add_column("Status", style="magenta")
    table.add_column("Dimension")
    table.add_column("Tags")

    for e in entries:
        status_icon = {
            "verified": "✅",
            "failed": "❌",
            "unverified": "⬜",
            "expired": "🔄",
        }.get(e.verification_status, "⬜")
        tags = ", ".join(e.tags) if e.tags else ""
        table.add_row(
            e.fid,
            e.latex[:50] if e.latex else "",
            f"{status_icon} {e.verification_status}",
            e.pint_dimension or "",
            tags,
        )

    console.print(table)


@verify_app.command("stats")
def stats_cmd(
    registry_path: str = typer.Option(
        "formula_registry.jsonl", "--registry", "-r",
    ),
):
    """Show registry statistics."""
    reg = _get_registry(registry_path)
    s = reg.stats()

    table = Table(title="Formula Registry Statistics")
    table.add_column("Metric", style="cyan")
    table.add_column("Value", style="white")

    table.add_row("Total entries", str(s.get("total", 0)))
    table.add_row("Schema version", str(s.get("schema_version", "?")))
    table.add_row("Registry path", s.get("path", "?"))

    by_status = s.get("by_status", {})
    for status, count in sorted(by_status.items()):
        table.add_row(f"  Status: {status}", str(count))

    table.add_row("Expired", str(s.get("expired", 0)))

    console.print(table)


@verify_app.command("add")
def add_cmd(
    fid: str = typer.Argument(..., help="Formula ID"),
    latex: str = typer.Argument(..., help="LaTeX formula string"),
    dimension: str = typer.Option(
        "", "--dim", "-d", help="Physical dimension (e.g. magnetic flux density)",
    ),
    source: str = typer.Option(
        "", "--source", "-s", help="Source reference key",
    ),
    tag: list[str] = typer.Option(
        [], "--tag", "-t", help="Tags (repeatable)",
    ),
    registry_path: str = typer.Option(
        "formula_registry.jsonl", "--registry", "-r",
    ),
):
    """Add a formula to the registry."""
    from hfpclawer.verify.registry import FormulaEntry

    reg = _get_registry(registry_path)
    entry = FormulaEntry(
        fid=fid,
        latex=latex,
        pint_dimension=dimension,
        source_keys=[source] if source else [],
        tags=tag,
    )

    if reg.add(entry):
        reg.save()
        console.print(f"[green]Added {fid}[/green]")
    else:
        console.print(f"[yellow]FID {fid} already exists (skipped)[/yellow]")


@verify_app.command("run")
def run_cmd(
    registry_path: str = typer.Option(
        "formula_registry.jsonl", "--registry", "-r",
    ),
    no_wolfram: bool = typer.Option(
        False, "--no-wolfram", help="Disable Wolfram Engine cross-validation",
    ),
    output: str = typer.Option(
        "", "--output", "-o", help="Save results to JSON file",
    ),
):
    """Run verification for all unverified formulas."""
    pipe = _get_pipeline(registry_path, wolfram=not no_wolfram)

    console.print("[cyan]Running L1→L5 verification pipeline...[/cyan]")

    if not no_wolfram:
        from hfpclawer.verify.engines.wolfram import is_available
        if is_available():
            console.print("  Wolfram Engine: [green]available[/green]")
        else:
            console.print("  Wolfram Engine: [yellow]unavailable (skip)[/yellow]")

    results = pipe.run_all()
    pipe.registry.save()

    # Print summary
    passed = sum(1 for r in results if r.passed)
    failed = sum(1 for r in results if not r.passed)

    table = Table(title=f"Verification Results ({len(results)} layers)")
    table.add_column("FID", style="cyan")
    table.add_column("Layer", style="magenta")
    table.add_column("Status", style="white")
    table.add_column("Detail")

    for r in results:
        icon = "✅" if r.passed else "❌"
        detail = r.detail[:60] if r.detail else ""
        table.add_row(r.fid, r.layer, icon, detail)

    console.print(table)
    console.print(f"\n[bold]{passed} passed, {failed} failed[/bold]")

    # Save to file if requested
    if output:
        pipe.save_results(output)
        console.print(f"Results saved to [cyan]{output}[/cyan]")


@verify_app.command("fid")
def fid_cmd(
    formula_id: str = typer.Argument(..., help="Formula ID to verify"),
    registry_path: str = typer.Option(
        "formula_registry.jsonl", "--registry", "-r",
    ),
    no_wolfram: bool = typer.Option(
        False, "--no-wolfram", help="Disable Wolfram Engine",
    ),
):
    """Verify a single formula by FID."""
    reg = _get_registry(registry_path)
    entry = reg.get(formula_id)

    if entry is None:
        console.print(f"[red]FID '{formula_id}' not found[/red]")
        raise typer.Exit(1)

    console.print(f"[bold]Verifying:[/bold] {entry.fid}")
    console.print(f"  LaTeX:  {entry.latex}")
    console.print(f"  Dim:    {entry.pint_dimension or '(none)'}")
    console.print(f"  Status: {entry.verification_status}")
    console.print()

    pipe = _get_pipeline(registry_path, wolfram=not no_wolfram)
    results = pipe.verify_entry(entry)

    table = Table(title=f"Verification Results for {formula_id}")
    table.add_column("Layer", style="magenta")
    table.add_column("Status", style="white")
    table.add_column("Detail")

    for r in results:
        icon = "✅" if r.passed else "❌"
        detail = r.detail[:80] if r.detail else ""

        # Show CAS proof details
        if r.cas and r.cas.proof_method:
            detail += f" [dim]({r.cas.proof_method})[/dim]"

        table.add_row(r.layer, icon, detail)

    console.print(table)

    # Update and save
    pipe.registry.save()


@verify_app.command("check")
def check_cmd(
    latex: str = typer.Argument(..., help="LaTeX formula to validate"),
):
    """Ad-hoc LaTeX syntax check and SymPy roundtrip."""
    from hfpclawer.verify.consistency import check_latex

    result = check_latex(latex)

    table = Table(title="LaTeX Syntax Check")
    table.add_column("Check", style="cyan")
    table.add_column("Result", style="white")

    table.add_row("Input", latex[:60])
    table.add_row("Parseable", "✅ Yes" if result.passed else "❌ No")
    table.add_row("SymPy output", result.sympy_latex[:60] if result.sympy_latex else "")
    table.add_row("Method", result.method)
    table.add_row("Symbols", str(result.symbol_count))
    table.add_row("Detail", result.detail)

    console.print(table)


@verify_app.command("cross")
def cross_cmd(
    formula_id: str = typer.Argument(..., help="Formula ID for CAS cross-validation"),
    registry_path: str = typer.Option(
        "formula_registry.jsonl", "--registry", "-r",
    ),
):
    """Run CAS cross-validation only (L1b)."""
    from hfpclawer.verify.engines.wolfram import is_available

    if not is_available():
        console.print("[red]Wolfram Engine not available[/red]")
        raise typer.Exit(1)

    reg = _get_registry(registry_path)
    entry = reg.get(formula_id)

    if entry is None:
        console.print(f"[red]FID '{formula_id}' not found[/red]")
        raise typer.Exit(1)

    pipe = _get_pipeline(registry_path, wolfram=True)

    # Run L1 first
    l1 = pipe.run_l1(entry)
    if not l1.passed:
        console.print("[red]L1 (SymPy) failed — cannot cross-validate[/red]")
        raise typer.Exit(1)

    console.print(f"[cyan]SymPy OK: {l1.sympy_latex[:60]}...[/cyan]")

    # Run L1b
    l1b = pipe.run_l1b(entry)

    if l1b.cas:
        cas = l1b.cas
        console.print()
        table = Table(title=f"CAS Cross-Validation: {formula_id}")
        table.add_column("Field", style="cyan")
        table.add_column("Value")

        eq_icon = "✅" if cas.equivalent else "❌"
        table.add_row("Equivalent", f"{eq_icon} {cas.equivalent}")
        table.add_row("Proof method", cas.proof_method or "N/A")
        table.add_row("Engine A", cas.engine_a)
        table.add_row("Engine B", cas.engine_b or "N/A")
        table.add_row("SymPy result", cas.sympy_result[:60] if cas.sympy_result else "")
        table.add_row("Wolfram result", cas.wolfram_result[:60] if cas.wolfram_result else "")
        if cas.diff:
            table.add_row("Diff (A-B)", cas.diff[:60])

        console.print(table)
    else:
        console.print(f"[yellow]L1b: {l1b.detail}[/yellow]")


@verify_app.command("report")
def report_cmd(
    formula_id: str = typer.Argument(..., help="Formula ID to report on"),
    registry_path: str = typer.Option(
        "formula_registry.jsonl", "--registry", "-r",
    ),
    no_wolfram: bool = typer.Option(
        False, "--no-wolfram", help="Disable Wolfram Engine",
    ),
    qmd: bool = typer.Option(
        False, "--qmd", help="Generate full Quarto .qmd (default: LaTeX snippet)",
    ),
    title: str = typer.Option(
        "", "--title", "-t", help="Document title (--qmd mode only)",
    ),
):
    """Generate a verification report (LaTeX snippet or Quarto .qmd).

    \b
    Examples:
      hfpclawer verify report eq:biot-savart                      # LaTeX snippet to stdout
      hfpclawer verify report eq:biot-savart --qmd > report.qmd   # Quarto .qmd
      quarto render report.qmd --to pdf                           # One-click PDF
    """
    reg = _get_registry(registry_path)
    entry = reg.get(formula_id)

    if entry is None:
        console.print(f"[red]FID '{formula_id}' not found[/red]")
        raise typer.Exit(1)

    # Run verification
    pipe = _get_pipeline(registry_path, wolfram=not no_wolfram)
    results = pipe.verify_entry(entry)
    pipe.registry.save()

    # Generate report
    console.print(f"[cyan]Generating report for {formula_id}...[/cyan]")

    if qmd:
        output = _generate_qmd_report(entry, results, title=title)
        print(output)
    else:
        output = _generate_latex_report(entry, results)
        # Wrap in \begin{document}...\end{document} with minimal preamble
        print(r"\documentclass{article}")
        print(r"\usepackage{booktabs}")
        print(r"\usepackage{amsmath,amssymb}")
        print(r"\usepackage[UTF8]{ctex}")
        print(r"\begin{document}")
        print(output)
        print(r"\end{document}")

