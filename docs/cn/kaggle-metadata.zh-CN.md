# Kaggle 元数据部署指南

> **中文版说明**：本文档与英文版 `docs/kaggle-metadata.md` 对照阅读。行数大致对齐。

## 概述

`hfpclawer[arxiv]` 提供两种离线 arXiv 元数据搜索方式：
1. **OAI-PMH 方式**（默认推荐）：无需任何 API Key，每日增量同步，适合快速搭建
2. **Kaggle JSONL 方式**（备选）：单次下载 ~5.3GB 全量元数据，构建 ~11GB 本地 FTS5 全文索引

> ⚠️ **PyPI 限制说明**：`pip install hfpclawer[arxiv]` 只是声明命名空间，**不会自动安装** `arxiv-metadata-service`（PyPI 不支持 `git+https` 依赖）。请根据下方步骤**手动 `git clone` 后安装**。

## 手动安装 arxiv-metadata-service

```bash
# 克隆仓库
git clone https://github.com/diamond2nv/arxiv-metadata-service.git
cd arxiv-metadata-service

# 安装
pip install -e .

# 验证
python arxiv_meta_cli.py --help
```

## 存储空间需求

| 方式 | 大小 | 格式 | 说明 |
|:----|:-----|:-----|:-----|
| **Kaggle JSONL** | ~5.3 GB | 单 `.jsonl` 文件 | 全量快照，每周更新 |
| **OAI-PMH SQLite+FTS5** | ~11 GB | SQLite 数据库+FTS5 索引 | 每日增量同步，搜索更快，无需 API Key |

Kaggle 适合快速一次性搭建，OAI-PMH 适合长期使用和增量更新。请根据你的磁盘空间和网络条件选择。

## Kaggle 配置步骤

### 1. 安装 Kaggle CLI

```bash
pip install kaggle
```

### 2. 获取 Kaggle API Token

1. 登录 [kaggle.com](https://www.kaggle.com)
2. 进入 **Account → API → Create New API Token**
3. 下载 `kaggle.json`

### 3. 配置 Token

```bash
# Linux / macOS
mkdir -p ~/.kaggle
mv ~/Downloads/kaggle.json ~/.kaggle/
chmod 600 ~/.kaggle/kaggle.json
```

### 4. 下载 arXiv 数据集

```bash
# 约 5.3 GB 下载
kaggle datasets download Cornell-University/arxiv
unzip arxiv.zip -d data/
# 结果: data/arxiv_metadata.jsonl (~5.3 GB, ~300万篇论文)
```

### 5. 导入到 hfpclawer

```bash
# Kaggle JSONL → hfpapers SQLite 存储
python scripts/import_arxiv_metadata.py --jsonl data/arxiv_metadata.jsonl
```

### 6. 验证

```bash
hfpclawer store stats
# 应有: ~300 万篇论文已导入
```

## OAI-PMH 替代方案（无需 API Key，每日增量）

如果不想用 Kaggle：

```bash
pip install hfpclawer[arxiv]  # 安装 arxiv-metadata-service
hfpclawer arxiv download --tier 1  # 启动 OAI-PMH 下载（第1层：约500万篇）
```

OAI-PMH 从 arXiv 免费 OAI 端点直接下载元数据，构建本地 FTS5 索引（~11 GB），支持增量同步（`--incremental 7`）和断点续传。

## 故障排除

| 问题 | 解决方案 |
|:----|:---------|
| `kaggle: command not found` | 运行 `pip install kaggle`，确保 `~/.local/bin` 在 PATH 中 |
| Kaggle 下载报 403 | 检查 `~/.kaggle/kaggle.json` 是否存在且 `chmod 600` |
| 磁盘空间不足 | Kaggle: 下载 5.3GB + 解压 5.3GB。OAI-PMH: 最终 DB ~11GB。确保至少 20GB 可用空间 |
| OAI-PMH 下载慢 | 这是预期的——arXiv 限制 1 query/4s。第1层约500万篇大约需要12-24小时，支持断点续传 |
