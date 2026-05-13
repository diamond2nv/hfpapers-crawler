# 网络依赖与端口用途

hfpclawer 项目使用的所有外部网络连接、站点、端口和协议清单。

## 外部站点

| 站点 | 协议 | 端口 | 用途 | 必需？ |
|------|------|------|------|--------|
| `export.arxiv.org` | HTTP | 80 | arXiv OAI-PMH 元数据下载、arXiv API 搜索 | ✅ |
| `huggingface.co` | HTTPS | 443 | `hf papers search` CLI 调用（论文搜索 API） | ❌ 可替换为 `arxiv_local` 或 `arxiv_api` |
| `api.openreview.net` | HTTPS | 443 | OpenReview API 搜索 | ❌ 可选来源 |
| `arxiv.org` | HTTPS | 443 | PDF 下载（`hfpclawer download`） | ❌ 仅下载 |
| `www.openarchives.org` | HTTP | 80 | OAI-PMH 协议定义（XML 命名空间） | ❌ 仅运行时参考 |
| `gitlab.zhejianglab.com` | HTTPS | 443 | `[arxiv]` 额外依赖安装（私有 GitLab） | ❌ 仅本地开发 |
| `pypi.org` | HTTPS | 443 | `pip install` 包依赖下载 | ✅ 首次安装 |
| `files.pythonhosted.org` | HTTPS | 443 | pip 包文件下载 | ✅ 首次安装 |

## 端口用途（MCP Server）

| 端口 | 协议 | 模式 | 用途 |
|------|------|------|------|
| 8765（默认） | HTTP/TCP | HTTP | MCP HTTP 模式监听端口（`hfpclawer mcp --mode http`） |
| — | stdio | stdio | MCP stdio 模式（默认，通过 stdin/stdout 通信） |

## 防火墙配置参考

用于内部网络时，需要开放以下端口：

### 出站

```
# 核心必需
tcp/80   → export.arxiv.org         # arXiv API 搜索
tcp/443  → huggingface.co           # HF paper 搜索
tcp/443  → pypi.org                 # pip install
tcp/443  → files.pythonhosted.org   # pip 文件下载

# 可选
tcp/443  → api.openreview.net       # OpenReview 搜索
tcp/443  → arxiv.org                # PDF 下载
```

### 入站（仅 HTTP 模式）

```
tcp/8765 → MCP HTTP Server（可选，默认仅 localhost）
```

## 代理配置

设置 HTTPS_PROXY 环境变量：
```bash
export HTTPS_PROXY=http://proxy:8080
```

`pip install` 会自动使用代理。`requests` 库会自动读取 `HTTPS_PROXY` 环境变量。
