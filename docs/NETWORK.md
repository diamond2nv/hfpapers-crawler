# Network Dependencies and Port Usage

Inventory of all external network connections, sites, ports, and protocols used by the hfpclawer project.

## External Sites

| Site | Protocol | Port | Purpose | Required? |
|------|----------|------|---------|-----------|
| `export.arxiv.org` | HTTP | 80 | arXiv OAI-PMH metadata download, arXiv API search | ✅ |
| `huggingface.co` | HTTPS | 443 | `hf papers search` CLI call (paper search API) | ❌ Replaceable with `arxiv_local` or `arxiv_api` |
| `api.openreview.net` | HTTPS | 443 | OpenReview API search | ❌ Optional source |
| `arxiv.org` | HTTPS | 443 | PDF download (`hfpclawer download`) | ❌ Download only |
| `www.openarchives.org` | HTTP | 80 | OAI-PMH protocol definition (XML namespace) | ❌ Runtime reference only |
| `gitlab.zhejianglab.com` | HTTPS | 443 | `[arxiv]` extra dependency install (private GitLab) | ❌ Local development only |
| `pypi.org` | HTTPS | 443 | `pip install` package dependency download | ✅ First install |
| `files.pythonhosted.org` | HTTPS | 443 | pip package file download | ✅ First install |

## Port Usage (MCP Server)

| Port | Protocol | Mode | Purpose |
|------|----------|------|---------|
| 8765 (default) | HTTP/TCP | HTTP | MCP HTTP mode listen port (`hfpclawer mcp --mode http`) |
| — | stdio | stdio | MCP stdio mode (default, communicates via stdin/stdout) |

## Firewall Configuration Reference

For use within an internal network, the following must be opened:

### Outbound

```
# Core required
tcp/80   → export.arxiv.org         # arXiv API search
tcp/443  → huggingface.co           # HF paper search
tcp/443  → pypi.org                 # pip install
tcp/443  → files.pythonhosted.org   # pip file download

# Optional
tcp/443  → api.openreview.net       # OpenReview search
tcp/443  → arxiv.org                # PDF download
```

### Inbound (HTTP mode only)

```
tcp/8765 → MCP HTTP Server (optional, localhost only by default)
```

## Proxy Configuration

Set the HTTPS_PROXY environment variable:
```bash
export HTTPS_PROXY=http://proxy:8080
```

`pip install` uses the proxy automatically. The `requests` library reads the `HTTPS_PROXY` environment variable automatically.
