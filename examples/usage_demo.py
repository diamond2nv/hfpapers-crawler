#!/usr/bin/env python3
"""
hfpapers-clawler 使用示例

安装:
    pip install hfpclawer

用法:
    python examples/usage_demo.py
"""
import json
import tempfile
import os

print("=" * 60)
print("hfpapers-clawler API 使用示例")
print("=" * 60)


# ─── 1. 基础配置 ─────────────────────────────
from hfpapers.config import load_config, get

# load_config() automatically reads config.yaml from the project root
# Override with _TEST_HFPAPERS_CONFIG env var for tests
cfg = load_config()
print(f"\n1. 配置加载: {len(cfg)} 个顶级键")
print(f"   搜索维度: {cfg.get('search', {}).get('queries', [{'query': 'N/A'}])[0]['query']}")
print(f"   相关度阈值: {get('classification.threshold_pass')}")


# ─── 2. Paper Store ──────────────────────────
from hfpapers.paper_store import (
    PaperStore, PaperRecord,
    ensure_paper, store_stats, get_store,
)

# 使用临时数据库
with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
    db_path = f.name

try:
    store = PaperStore(db_path=db_path)

    # 添加论文
    rec = PaperRecord(
        title="Fourier Neural Operator for PDEs",
        abstract="Learning PDE solution operators with Fourier transforms in the neural network framework",
        year=2023,
        source="demo",
        relevance=90,
    )
    sf_id = store.upsert_paper(rec)
    store.add_identifier(sf_id, "arxiv", "2010.08895", source="demo")

    print(f"\n2. Paper Store: sf_id={sf_id}")
    got = store.get_paper_by_id(sf_id)
    print(f"   论文: {got.title}")
    ids = store.get_identifiers(sf_id)
    for i in ids:
        print(f"   标识符: {i.id_type}={i.id_value}")


    # ─── 3. 搜索论文 ─────────────────────────────
    # 添加更多论文用于搜索测试
    sf2 = store.upsert_paper(PaperRecord(title="DeepONet: Learning Operators", relevance=80))
    store.add_identifier(sf2, "arxiv", "1910.03193")

    papers = store.search_papers("Fourier")
    print(f"\n3. 搜索 'Fourier': 找到 {len(papers)} 篇")
    for p in papers:
        print(f"   [{p.relevance}] {p.title}")


    # ─── 4. 统计 ─────────────────────────────────
    stats = store.stats()
    print(f"\n4. 存储统计:")
    print(f"   论文总数: {stats['papers_total']}")
    print(f"   已验证: {stats['papers_verified']}")
    print(f"   标识符: {stats['identifiers_total']}")


    # ─── 5. 高层次接口 ──────────────────────────
    from hfpapers.paper_store import ensure_paper

    sf_id3, is_new = ensure_paper(
        arxiv_id="2301.11167",
        title="Physics-Informed Neural Networks",
        source="demo",
        relevance=85,
    )
    print(f"\n5. ensure_paper: sf_id={sf_id3} is_new={is_new}")


    # ─── 6. 硬件探针 ─────────────────────────────
    from hfpapers.hardware import HardwareProbe

    hw = HardwareProbe()
    print(f"\n6. 硬件探针: {hw.summary()}")
    print(f"   PDF转换器: {'可用' if hw.use_pdf_converter else '不可用'}")
    print(f"   BERT加速: {'可用' if hw.use_bert else '不可用（需CUDA）'}")


    # ─── 7. CLI 命令 ─────────────────────────────
    from typer.testing import CliRunner
    from hfpapers.cli import app

    runner = CliRunner()
    result = runner.invoke(app, ["config"])
    print(f"\n7. CLI 'hfpclawer config': exit_code={result.exit_code}")


    # ─── 8. MCP 集成 ─────────────────────────────
    from hfpapers.mcp_server import MCP_TOOLS
    print(f"\n8. MCP 工具 ({len(MCP_TOOLS)} 个):")
    for name, info in sorted(MCP_TOOLS.items()):
        desc = info.get("description", "")[:60]
        print(f"   {name}: {desc}...")

finally:
    # 清理
    if os.path.exists(db_path):
        os.unlink(db_path)
    if os.path.exists(db_path + "-wal"):
        os.unlink(db_path + "-wal")

print(f"\n{'=' * 60}")
print("✅ Demo 运行成功")
print(f"{'=' * 60}")
