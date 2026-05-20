# Citation Audit Phase 2: 基于 ARS 代码的三索引降级管道

**生成日期:** 2026-05-20
**关联:** Phase D (发布与分发) — 在 v0.5.0 (Hermes 集成) 之后

## 目标

从 `academic-research-skills` (ARS, Imbad0202, CC BY-NC 4.0) 复用到 `hfpclawer/citation_audit.py`，构建 L1→L2→L3 三索引降级管道。

**ARS 复用的 ARS 组件:**
1. `_text_similarity.py` → 100% 复制到 `hfpclawer/_text_similarity.py`（纯函数 44 行）
2. `semantic_scholar_client.py` → 参考架构，简化为 `citation_audit_s2.py`（~150 行）
3. `openalex_client.py` → 参考架构，简化为 `citation_audit_oa.py`（~100 行）

**许可证:** CC BY-NC 4.0 — `README.md` 中添加 Attribution 声明。

## 执行步骤

### P1: 复制 `_text_similarity.py`（~15 分钟）

**文件:** `hfpclawer/_text_similarity.py`
```
_path = "hfpclawer/_text_similarity.py"
content = (从 ARS 脚本目录复制)
```

**文件:** `tests/test_text_similarity.py`
```
- 从 ARS `test_text_similarity.py` 复制并适配
- 测试 normalize_title(), title_similarity(), exact_match()
```

### P2: 重写 `citation_audit.py` → 三索引降级管道（~30 分钟）

**`hfpclawer/citation_audit.py` 核心改动:**

```python
def check_citation(citation_text, *args):
    """统一入口: L1 → L2 → L3 降级"""
    # 1. L1: 本地 FTS5（现有逻辑，但评分改用 _text_similarity）
    result = check_citation_local(...)
    if result["found"]:
        return result
    
    # 2. L2: Semantic Scholar API（参考 ARS 的 SemanticScholarClient）
    result = check_citation_s2(...)
    if result["found"]:
        return result
    
    # 3. L3: OpenAlex API（参考 ARS 的 OpenAlexClient）
    result = check_citation_oa(...)
    return result  # 最终 fallback：可能 still not found
```

**CLI 接口改动:**
```
hfpclawer audit verify <citation>          # L1 → L2 → L3（默认）
hfpclawer audit verify <citation> --source local
hfpclawer audit verify <citation> --source s2
hfpclawer audit verify <citation> --source openalex
hfpclawer audit verify --list              # 可选来源
```

### P3: 添加 S2 + OpenAlex 客户端（~45 分钟）

**`hfpclawer/citation_audit_s2.py`（参考 ARS `semantic_scholar_client.py`）**

保留的核心设计:
- `lookup_by_doi(doi)` → 请求 `https://api.semanticscholar.org/graph/v1/paper/{doi}`
- `lookup_by_title(title)` → `/paper/search?query={title}&limit=5`
- rate-limit pacing (1 req/s)
- 429 退避 (retry-after)
- timeout=10s

去掉的: contamination_signals, outage_latch, DOI_MISMATCH Protocol

**`hfpclawer/citation_audit_oa.py`（参考 ARS `openalex_client.py`）**

保留的核心设计:
- `lookup_by_doi(doi)` → `https://api.openalex.org/works/doi:{doi}`
- `lookup_by_title(title)` → `/works?search={title}&per_page=5`
- Polite pool 限速 (0.1s)
- 429 退避

去掉的: Email header (可选保留), DOI_MISMATCH

### P4: 测试（~30 分钟）

- `tests/test_text_similarity.py` — 单元测试 `_text_similarity` 纯函数
- `tests/test_citation_audit_s2.py` — mock network requests
- `tests/test_citation_audit_oa.py` — mock network requests
- `tests/test_citation_audit.py` — 扩展现有 22 测试以覆盖 L2→L3 降级

### P5: README 许可证声明（~5 分钟）

在 `README.md` 和 `README.zh-CN.md` 中添加:

```markdown
## Acknowledgments

This project incorporates code adapted from:
- **academic-research-skills** by Cheng-I Wu
  (https://github.com/Imbad0202/academic-research-skills)
  - `hfpclawer/_text_similarity.py` — title normalization and similarity scoring
  - `hfpclawer/citation_audit_s2.py` — Semantic Scholar API client (architecture reference)
  - `hfpclawer/citation_audit_oa.py` — OpenAlex API client (architecture reference)
  Licensed under CC BY-NC 4.0 (https://creativecommons.org/licenses/by-nc/4.0/)
```

## 文件变更清单

| 操作 | 文件 | 行数估计 |
|------|------|---------|
| NEW | `hfpclawer/_text_similarity.py` | ~44 |
| NEW | `hfpclawer/citation_audit_s2.py` | ~150 |
| NEW | `hfpclawer/citation_audit_oa.py` | ~100 |
| EDIT | `hfpclawer/citation_audit.py` | ~+80 (三索引入口) |
| NEW | `tests/test_text_similarity.py` | ~50 |
| NEW | `tests/test_citation_audit_s2.py` | ~80 |
| NEW | `tests/test_citation_audit_oa.py` | ~60 |
| EDIT | `tests/test_citation_audit.py` | ~+40 (降级测试) |
| EDIT | `README.md` | ~+10 (Acknowledgments) |
| EDIT | `README.zh-CN.md` | ~+10 (致谢) |

总计: ~+12 文件, ~+620 行

## 执行顺序建议

```
P1 (复制 text_similarity) + P5 (README 声明) → P4 (测试) → P2 (三索引入口) → P3 (客户端) → P4 (测试)
```

建议先从 P1+P5 开始（快速收效），然后 P2→P3→P4（增量构建）。
