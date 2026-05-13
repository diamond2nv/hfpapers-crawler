# Hermes Agent Integration Example

hfpapers-clawler can be used directly within Hermes Agent.

## Installation

```bash
pip install hfpclawer
```

## MCP Server Integration

Register the MCP Server in Hermes Agent's `~/.hermes/config.yaml`:

```yaml
mcp:
  servers:
    hfpapers:
      command: "hfpclawer"
      args: ["mcp", "--port", "8765"]
      env:
        HF_TOKEN: "${HF_TOKEN}"
```

Hermes automatically discovers the following MCP tools:

| Tool | Description |
|------|-------------|
| `hfpclawer_search` | Search for new papers |
| `hfpclawer_download` | Download PDF |
| `hfpclawer_convert` | PDF → Markdown |
| `hfpclawer_info` | Query paper details |
| `hfpclawer_list` | List crawled papers |
| `hfpclawer_stats` | Crawler statistics |
| `hfpclawer_full` | Full pipeline |

## Usage Examples

### Search Papers

```
User: Search for the latest PDE neural operator papers
Hermes: Using hfpclawer_search tool...
Results: Found 3 new papers
- [85] 2010.08895 Fourier Neural Operator
- [75] 2003.03085 DeepONet
- [62] 2104.06458 Physics-Informed Neural Operator
```

### Paper Store Operations

```
User: List the paper store
Hermes: Using hfpclawer_list tool...
```

### Full Pipeline

```
User: Run the full pipeline
Hermes: Using hfpclawer_full tool...
```

## Python API Direct Usage

Use directly in Hermes Agent's `execute_code`:

```python
from hfpapers.paper_store import PaperStore, PaperRecord, ensure_paper
from hfpapers.hardware import HardwareProbe

# Hardware probe
hw = HardwareProbe()
print(f"Hardware: {hw.summary()}")

# Store a paper
sf_id, is_new = ensure_paper(
    arxiv_id="2301.11167",
    title="Physics-Informed Neural Networks",
    source="hermes",
    relevance=85,
)

# Search
store = PaperStore()
papers = store.search_papers("neural operator")
for p in papers:
    ids = store.get_identifiers(p.sf_id)
    id_str = ", ".join(f"{i.id_type}={i.id_value}" for i in ids)
    print(f"[{p.relevance}] {p.title[:50]} | {id_str}")
```

## CLI Direct Execution

Invoke directly via `terminal` within Hermes Agent:

```bash
hfpclawer search --dry-run
hfpclawer store stats
hfpclawer full --threshold 50
```
