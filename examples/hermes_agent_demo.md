# Hermes Agent 集成示例

hfpapers-clawler 可以直接在 Hermes Agent 中使用。

## 安装

```bash
pip install hfpclawer
```

## MCP Server 集成

在 Hermes Agent 的 `~/.hermes/config.yaml` 中注册 MCP Server：

```yaml
mcp:
  servers:
    hfpapers:
      command: "hfpclawer"
      args: ["mcp", "--port", "8765"]
      env:
        HF_TOKEN: "${HF_TOKEN}"
```

Hermes 自动发现以下 MCP 工具：

| 工具 | 描述 |
|------|------|
| `hfpclawer_search` | 搜索新论文 |
| `hfpclawer_download` | 下载 PDF |
| `hfpclawer_convert` | PDF → Markdown |
| `hfpclawer_info` | 查论文详情 |
| `hfpclawer_list` | 列出已爬取论文 |
| `hfpclawer_stats` | 爬虫统计 |
| `hfpclawer_full` | 全流程 pipeline |

## 使用示例

### 搜索论文

```
用户: 搜索最新的 PDE 神经算子论文
Hermes: 使用 hfpclawer_search 工具...
结果: 发现 3 篇新论文
- [85] 2010.08895 Fourier Neural Operator
- [75] 2003.03085 DeepONet
- [62] 2104.06458 Physics-Informed Neural Operator
```

### Paper Store 操作

```
用户: 列出论文库
Hermes: 使用 hfpclawer_list 工具...
```

### 全流程 Pipeline

```
用户: 运行全流程管道
Hermes: 使用 hfpclawer_full 工具...
```

## Python API 直接调用

在 Hermes Agent 的 `execute_code` 中直接使用：

```python
from hfpapers.paper_store import PaperStore, PaperRecord, ensure_paper
from hfpapers.hardware import HardwareProbe

# 硬件探测
hw = HardwareProbe()
print(f"Hardware: {hw.summary()}")

# 存储论文
sf_id, is_new = ensure_paper(
    arxiv_id="2301.11167",
    title="Physics-Informed Neural Networks",
    source="hermes",
    relevance=85,
)

# 搜索
store = PaperStore()
papers = store.search_papers("neural operator")
for p in papers:
    ids = store.get_identifiers(p.sf_id)
    id_str = ", ".join(f"{i.id_type}={i.id_value}" for i in ids)
    print(f"[{p.relevance}] {p.title[:50]} | {id_str}")
```

## CLI 直接执行

在 Hermes Agent 中直接用 `terminal` 调用：

```bash
hfpclawer search --dry-run
hfpclawer store stats
hfpclawer full --threshold 50
```
