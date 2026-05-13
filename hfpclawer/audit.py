"""audit.py — 数据源审计模块

提供：
  - run_audit(): 生成完整审计报告
  - cli_audit(): CLI 入口
"""

import json
import logging
import os
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional

from hfpapers.config import get as cfg_get

logger = logging.getLogger("hfpclawer.audit")


def _get_db_path() -> str:
    """获取 arxiv_meta.db 路径"""
    base = cfg_get("db.path", "data/arxiv_meta.db")
    if not os.path.isabs(base):
        base = os.path.join(os.getcwd(), base)
    return base


def _get_data_dir() -> str:
    """获取数据目录路径"""
    data_dir = cfg_get("paths.data_dir", "data")
    if not os.path.isabs(data_dir):
        data_dir = os.path.join(os.getcwd(), data_dir)
    return data_dir


def _get_state_paths(db_dir: str) -> list[dict]:
    """扫描 download_state JSON fallback 文件"""
    results = []
    for f in sorted(Path(db_dir).glob("*_download_state.json")):
        try:
            with open(f) as fp:
                state = json.load(fp)
            results.append({
                "file": str(f),
                "source": state.get("source", f.stem.replace("_download_state", "")),
                "status": state.get("status", "unknown"),
                "total_new": state.get("total_new", 0),
                "total_fetched": state.get("total_fetched", 0),
                "last_update": state.get("last_update", ""),
                "checksum": state.get("checksum", ""),
                "error": state.get("error", ""),
            })
        except (json.JSONDecodeError, OSError) as e:
            results.append({
                "file": str(f),
                "source": "unknown",
                "status": f"parse_error: {e}",
            })
    return results


def _get_jsonl_info(data_dir: str) -> Optional[dict]:
    """检查 arxiv_metadata.jsonl 文件状态"""
    jsonl_path = Path(data_dir) / "arxiv_metadata.jsonl"
    if jsonl_path.exists():
        size_mb = jsonl_path.stat().st_size / (1024 * 1024)
        line_count = 0
        for _ in open(jsonl_path, "rb"):
            line_count += 1
        return {
            "exists": True,
            "path": str(jsonl_path),
            "size_mb": round(size_mb, 1),
            "lines": line_count,
        }
    return {"exists": False, "path": str(jsonl_path)}


def run_paper_store_audit(store=None) -> dict:
    """审计 paper_store 论文质量（交叉验证、标识符分布）

    Args:
        store: PaperStore 实例，None 则用 get_store()

    Returns:
        dict with keys:
        - total_papers: 论文总数
        - verified_papers: 已验证论文数
        - with_code: 有代码的论文数
        - dual_id_papers: 有 arXiv + DOI 双标识符的论文数
        - identifier_types: 所有标识符类型列表
        - identifier_type_stats: [{type, count}, ...]
    """
    if store is None:
        from hfpapers.paper_store import get_store
        store = get_store()

    stats = store.stats()
    report = {
        "total_papers": stats["papers_total"],
        "verified_papers": stats["papers_verified"],
        "with_code": stats["papers_with_code"],
        "dual_id_papers": 0,
        "identifier_types": list(stats.get("identifiers_by_type", {}).keys()),
        "identifier_type_stats": [
            {"type": t, "count": c}
            for t, c in stats.get("identifiers_by_type", {}).items()
        ],
    }

    # 计算 dual_id_papers：既有 arxiv 又有 doi 标识符的论文数
    if report["total_papers"] > 0:
        with store._conn() as conn:
            row = conn.execute("""
                SELECT COUNT(*) FROM (
                    SELECT p.sf_id FROM papers p
                    JOIN identifiers i1 ON p.sf_id = i1.sf_id AND i1.id_type = 'arxiv'
                    JOIN identifiers i2 ON p.sf_id = i2.sf_id AND i2.id_type = 'doi'
                    GROUP BY p.sf_id
                )
            """).fetchone()
            report["dual_id_papers"] = row[0] if row else 0

    # 补充：已验证率
    if report["total_papers"] > 0:
        report["verified_ratio"] = round(report["verified_papers"] / report["total_papers"], 4)
        report["dual_id_ratio"] = round(report["dual_id_papers"] / report["total_papers"], 4)
    else:
        report["verified_ratio"] = 0.0
        report["dual_id_ratio"] = 0.0

    return report


def run_full_audit(db_path: str = None, data_dir: str = None) -> dict:
    """完整审计：arxiv_meta 数据源审计 + paper_store 论文质量审计"""
    meta_report = run_audit(db_path=db_path, data_dir=data_dir)
    store_report = run_paper_store_audit()
    return {
        "timestamp": meta_report["timestamp"],
        "arxiv_meta": meta_report,
        "paper_store": store_report,
    }


def format_paper_store_report(report: dict) -> str:
    """格式化为可读文本"""
    lines = []
    lines.append(f"\n📚 Paper Store 论文质量:")
    lines.append(f"  论文总数: {report['total_papers']:,}")
    lines.append(f"  已验证:   {report['verified_papers']:,} ({report.get('verified_ratio', 0)*100:.1f}%)")
    lines.append(f"  有代码:   {report['with_code']:,}")
    lines.append(f"  双 ID:    {report['dual_id_papers']:,} ({report.get('dual_id_ratio', 0)*100:.1f}%)")

    lines.append(f"\n  标识符分布:")
    for ts in report.get("identifier_type_stats", []):
        lines.append(f"    {ts['type']}: {ts['count']:,}")

    return "\n".join(lines)


def format_full_audit_report(report: dict) -> str:
    """完整审计报告"""
    lines = []
    lines.append("=" * 50)
    lines.append("📊 完整数据审计报告")
    lines.append(f"时间: {report['timestamp']}")
    lines.append("=" * 50)
    lines.append("")

    # arxiv_meta 部分
    meta = report.get("arxiv_meta", {})
    lines.append(f"📁 元数据源 (arxiv_meta.db)")
    lines.append(f"  DB: {meta.get('db_path', 'N/A')}")
    lines.append(f"  存在: {'✅' if meta.get('db_exists') else '❌'}")
    if meta.get("db_exists"):
        size = os.path.getsize(meta["db_path"]) / (1024 * 1024)
        lines.append(f"  大小: {size:.0f} MB")
        lines.append(f"  总计: {meta.get('total', 0):,} 篇")
        lines.append(f"  source 列: {'✅' if meta.get('has_source_column') else '❌'}")

        lines.append(f"\n  数据来源:")
        for src, info in meta.get("sources", {}).items():
            label = "legacy" if src == "unknown" else src
            lines.append(f"    [{label}] {info['count']:,} 篇")
            if info.get("first_import"):
                lines.append(f"      首次: {info['first_import']}")
            if info.get("last_import"):
                lines.append(f"      最近: {info['last_import']}")

    # state files
    state_files = meta.get("state_files", [])
    if state_files:
        lines.append(f"\n  状态文件:")
        for sf in state_files:
            lines.append(f"    {Path(sf['file']).name} → {sf['status']} ({sf['total_new']:,} 篇)")

    # JSONL
    jl = meta.get("jsonl", {})
    if jl:
        lines.append(f"\n  Kaggle JSONL: {'✅ ' + jl.get('path','') if jl.get('exists') else '❌ 不存在'}")

    # paper_store 部分
    lines.append("")
    ps = report.get("paper_store", {})
    lines.append(format_paper_store_report(ps))

    return "\n".join(lines)


def run_audit(db_path: str = None, data_dir: str = None) -> dict:
    """运行审计，返回完整报告 dict"""
    db_path = db_path or _get_db_path()
    data_dir = data_dir or _get_data_dir()

    report = {
        "timestamp": datetime.now().isoformat(),
        "db_path": db_path,
        "data_dir": data_dir,
        "db_exists": os.path.exists(db_path),
        "sources": {},
        "state_files": [],
        "jsonl": None,
        "total": 0,
    }

    if not report["db_exists"]:
        return report

    # 连接 DB
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    try:
        # 检查 source 列是否存在
        cols = [r["name"] for r in conn.execute("PRAGMA table_info(arxiv_meta)").fetchall()]
        has_source = "source" in cols
        report["has_source_column"] = has_source

        if has_source:
            # 各源统计
            rows = conn.execute(
                "SELECT source, COUNT(*) as cnt, MIN(imported_at) as first_import, "
                "MAX(imported_at) as last_import FROM arxiv_meta GROUP BY source"
            ).fetchall()
            for r in rows:
                report["sources"][r["source"] if r["source"] else "unknown"] = {
                    "count": r["cnt"],
                    "first_import": r["first_import"],
                    "last_import": r["last_import"],
                }

        # 总计
        report["total"] = conn.execute("SELECT COUNT(*) FROM arxiv_meta").fetchone()[0]

        # 无 source 列时的 fallback
        if not has_source:
            report["sources"]["legacy"] = {"count": report["total"], "note": "无 source 列，所有数据标记为 legacy"}
    finally:
        conn.close()

    # state files
    db_dir = os.path.dirname(db_path)
    report["state_files"] = _get_state_paths(db_dir)

    # JSONL 检查
    report["jsonl"] = _get_jsonl_info(data_dir)

    return report


def format_audit_report(report: dict) -> str:
    """格式化为可读文本"""
    lines = []
    lines.append("=" * 50)
    lines.append("📊 数据源审计报告")
    lines.append(f"时间: {report['timestamp']}")
    lines.append("=" * 50)
    lines.append("")

    # DB
    lines.append(f"📁 数据库: {report['db_path']}")
    lines.append(f"   存在: {'✅' if report['db_exists'] else '❌'}")
    if report["db_exists"]:
        size = os.path.getsize(report["db_path"]) / (1024 * 1024)
        lines.append(f"   大小: {size:.0f} MB")
        lines.append(f"   总计: {report['total']:,} 篇")

    if not report["db_exists"]:
        return "\n".join(lines)

    # 各源
    lines.append(f"\n   source 列: {'✅' if report.get('has_source_column') else '❌'}")
    lines.append(f"\n📂 数据来源:")
    for src, info in report.get("sources", {}).items():
        label = "legacy" if src == "unknown" else src
        lines.append(f"  [{label}]")
        lines.append(f"    论文数: {info['count']:,}")
        if info.get("first_import"):
            lines.append(f"    首次导入: {info['first_import']}")
        if info.get("last_import"):
            lines.append(f"    最近导入: {info['last_import']}")
        if info.get("note"):
            lines.append(f"    备注: {info['note']}")

    # state files
    lines.append(f"\n📄 状态文件 (download_state 备份):")
    for sf in report.get("state_files", []):
        lines.append(f"  📍 {Path(sf['file']).name}")
        lines.append(f"     来源: {sf['source']}")
        lines.append(f"     状态: {sf['status']}")
        if sf.get("total_new"):
            lines.append(f"     论文数: {sf['total_new']:,}")
        if sf.get("last_update"):
            lines.append(f"     最后更新: {sf['last_update']}")
        if sf.get("checksum"):
            lines.append(f"     checksum: {sf['checksum'][:20]}...")
        if sf.get("error"):
            lines.append(f"     ⚠️ 错误: {sf['error']}")

    if not report.get("state_files"):
        lines.append(f"  暂无状态文件")

    # JSONL
    jl = report.get("jsonl", {})
    lines.append(f"\n📦 Kaggle JSONL 文件:")
    if jl.get("exists"):
        lines.append(f"  ✅ 存在: {jl['path']}")
        lines.append(f"     大小: {jl['size_mb']} MB")
        lines.append(f"     行数: {jl['lines']:,}")
    else:
        lines.append(f"  ❌ 不存在")

    return "\n".join(lines)
