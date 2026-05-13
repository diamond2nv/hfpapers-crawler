"""
conftest.py — 全项目共享 fixture
"""

import os
import sys
import tempfile
import pytest

# ─── 测试专用配置 ───
@pytest.fixture(autouse=True)
def test_env():
    """隔离测试环境：临时目录 + 临时数据库"""
    old_cwd = os.getcwd()
    with tempfile.TemporaryDirectory() as tmpdir:
        os.chdir(tmpdir)
        # 创建最小 config.yaml
        cfg_path = os.path.join(tmpdir, "config.yaml")
        with open(cfg_path, "w") as f:
            f.write("""
search:
  max_per_dim: 5
  queries:
    - query: "neural operator"
      category: neural-operator
keywords:
  include_high:
    - "neural operator"
    - "pde"
  exclude:
    - "quantum"
    - "llm"
classification:
  threshold_pass: 30
  title_similarity_min: 0.40
paths:
  data_dir: "data"
  pdf_dir: "pdfs"
  md_dir: "mds"
  global_dedup: "crawled.json"
""")
        # 环境变量指向测试配置（config.py 的 load_config() 会优先用这个）
        os.environ["_TEST_HFPAPERS_CONFIG"] = cfg_path
        # 强制重新加载配置，确保 fixture 的 config 生效
        import hfpapers.config as _cfg
        _cfg._config_cache = None
        _cfg.load_config(reload=True)
        # 重置全局单例，避免跨测试污染
        import hfpapers.paper_store as _ps
        _ps._store_instance = None
        _ps._crossref_instance = None
        yield tmpdir
        os.chdir(old_cwd)
        # 清理全局单例（方便后续测试）
        import hfpapers.paper_store as _ps
        _ps._store_instance = None
        _ps._crossref_instance = None


@pytest.fixture
def paper_store():
    """临时 paper_store 实例（在内存中）"""
    import tempfile
    from hfpapers.paper_store import PaperStore
    db_fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(db_fd)
    store = PaperStore(db_path=db_path)
    yield store
    try:
        if os.path.exists(db_path):
            os.unlink(db_path)
            if os.path.exists(db_path + "-wal"):
                os.unlink(db_path + "-wal")
    except Exception:
        pass
