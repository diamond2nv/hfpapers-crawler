# 网络依赖与端口用途

hfpclawer 项目中所有外部网络连接的站点、端口和协议清单。

## 外部站点

| 站点 | 协议 | 端口 | 用途 | 必需？ |
|------|------|------|------|--------|
| `export.arxiv.org` | HTTP | 80 | arXiv OAI-PMH 元数据下载、arXiv API 搜索 | ✅ |
| `huggingface.co` | HTTPS | 443 | `hf papers search` CLI 调用（论文搜索 API） | ❌ 用 `arxiv_local` 或 `arxiv_api` 可替代 |
| `api.openreview.net` | HTTPS | 443 | OpenReview API 搜索 | ❌ 可选源 |
| `arxiv.org` | HTTPS | 443 | PDF 下载（`hfpclawer download`） | ❌ 仅下载时 |
| `www.openarchives.org` | HTTP | 80 | OAI-PMH 协议定义（XML namespace） | ❌ 仅运行时引用 |
| `gitlab.zhejianglab.com` | HTTPS | 443 | `[arxiv]` extra 依赖安装（内网 GitLab） | ❌ 仅本地开发 |
| `pypi.org` | HTTPS | 443 | `pip install` 包依赖下载 | ✅ 首次安装 |
| `files.pythonhosted.org` | HTTPS | 443 | pip 包文件下载 | ✅ 首次安装 |

## 端口使用（MCP Server）

| 端口 | 协议 | 模式 | 用途 |
|------|------|------|------|
| 8765 (默认) | HTTP/TCP | HTTP | MCP HTTP 模式监听端口（`hfpclawer mcp --mode http`） |
| — | stdio | stdio | MCP stdio 模式（默认，通过 stdin/stdout 通信） |

## 防火墙配置参考

如在内网环境使用，需开放：

### 出站（OUTBOUND）

```
# 核心必需
tcp/80   → export.arxiv.org         # arXiv API 搜索
tcp/443  → huggingface.co           # HF 论文搜索
tcp/443  → pypi.org                 # pip 安装
tcp/443  → files.pythonhosted.org   # pip 文件下载

# 可选
tcp/443  → api.openreview.net       # OpenReview 搜索
tcp/443  → arxiv.org                # PDF 下载
```

### 入站（INBOUND，仅 HTTP 模式时）

```
tcp/8765 → MCP HTTP Server（可选，默认仅 localhost）
```

## 代理配置

设置 HTTPS_PROXY 环境变量即可：
```bash
export HTTPS_PROXY=http://proxy:8080
```

`pip install` 自动使用代理。`requests` 库自动读取 `HTTPS_PROXY` 环境变量。
