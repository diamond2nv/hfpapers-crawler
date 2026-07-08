# hfpclawer ↔ Zotero Integration — Pre-Plan Research

**Date:** 2026-07-12
**Author:** Hermes Agent (hfpclawer-cron + codegraph)
**Status:** Pre-plan research (awaiting user review)

---

## 1. Motivation

hfpclawer currently crawls papers from arXiv/HF/OpenReview/PwC and stores them in `paper_store` (SQLite). However:

- **5+ years of Zotero library** — user already has thousands of curated papers that hfpclawer should **read from** (avoid re-crawling)
- **Zotero browser plugin** — the ideal channel for capturing PDFs from Sci-Hub, publisher sites, etc. (hfpclawer should **write to** Zotero, not bypass it)
- **WebDAV file access** — Zotero syncs PDFs via WebDAV; hfpclawer can consume them without web_scrape
- **Dual ecosystem** — hfpclawer handles automated crawling, Zotero handles human-curated + browser-captured papers

---

## 2. Zotero Ecosystem Mapping

### 2.1 Repos Cloned for Pre-Plan

All 6 repos cloned to `~/Documents/Gitlab/Agentic4Sci/`:

| Repo | Cloned From | Size | Purpose |
|------|-------------|------|---------|
| `zotero/` | GitCode (gh_mirrors) | 55M | Desktop app source (reference) |
| `pyzotero/` | GitHub | 2.3M | **Python API client** — primary integration point |
| `zotero-better-bibtex/` | GitHub | 131M | JSON-RPC plugin on port 23119 |
| `ZotPilot/` | GitHub | 9.0M | **AI Agent + Zotero MCP** — reference architecture |
| `zotero-scipdf/` | GitCode | 748K | PDF metadata extraction plugin |
| `WPS-Zotero/` | GitCode | 444K | Proxy architecture pattern |

### 2.2 API Layers (Port 23119 Ecosystem)

```
localhost:23119
  ├── /api/...                   — Zotero built-in REST API (read-only)
  ├── /better-bibtex/json-rpc    — Better BibTeX JSON-RPC (citation keys, export)
  └── /debug-bridge/execute      — Debug bridge (arbitrary JS execution in Zotero)

api.zotero.org
  └── /users/{id}/items          — Full CRUD via pyzotero remote mode
```

### 2.3 Key Libraries Available (Python)

| Library | pip Install | Read | Write | MCP | Notes |
|---------|-------------|------|-------|-----|-------|
| `pyzotero` | `pip install pyzotero` | ✅ local (23119) | ✅ remote (api.zotero.org) | ✅ built-in | Primary integration lib |
| `ZotPilot` | Source build | ✅ SQLite RO + Web API | ✅ Web API | ✅ 18 tools | Reference for dual-db pattern |
| `zotero-local-write-api` | Zotero plugin | — | ✅ local (23119) | — | Optional for offline write |

---

## 3. Code-Derived Findings

### 3.1 pyzotero Architecture (from codegraph)

**`Zotero(library_id, library_type, local=True)`**:
- Local: connects to `http://localhost:23119` (strips `/api` prefix automatically)
- Remote: connects to `https://api.zotero.org/users/{id}`
- **Read methods** (available in both modes): `items()`, `top()`, `item(key)`, `children(key)`, `file(key)`, `dump(key)`, `collections()`, `tags()`, `fulltext_item(key)`
- **Write methods** (remote only): `create_items(payload)`, `update_item(payload)`, `delete_item(key)`, `attachment_simple(paths)`, `add_tags(item, *tags)`, `delete_tags(*tags)`, `addto_collection(collection, payload)`
- **Write token**: Every write needs `Zotero-Write-Token: {uuid4_hex}`
- **Concurrency**: `If-Unmodified-Since-Version` header for optimistic locking
- **Tag format**: `[{"tag": "hfpclawer", "type": 1}]` — type 1 = automatic

**pyzotero MCP server**: 10 tools (search, get_item, get_children, list_collections, list_tags, get_fulltext + 4 Semantic Scholar tools). Uses `local=True` exclusively. Great for read-only integration.

### 3.2 ZotPilot Architecture (from codegraph)

**Dual-database pattern**:

| Path | Mode | Technology | Purpose |
|------|------|-----------|---------|
| READ | SQLite RO | `file:///zotero.sqlite?mode=ro&immutable=1` | Fast bulk metadata, storage paths |
| READ | Web API (pyzotero) | `api.zotero.org` | Structured queries, item details |
| WRITE | Web API (pyzotero) | `api.zotero.org` | Create/update/delete items & tags |
| CAPTURE | Bridge+Chrome Ext | `localhost:2619` → Chrome Connector | Browser-assisted paper capture |

**Key queries from ZotPilot SQLite read:**
- `items` + `itemData` + `itemDataValues` + `fields` — EAV pattern for metadata
- `itemAttachments` — `linkMode`, `contentType`, `path` for PDF paths
- `itemTags` + `tags` — tag linking
- `storage/{attachmentKey}/{filename}` — PDF path resolution from `linkMode=0 (IMPORTED_FILE)`

### 3.3 Better BibTeX (from codegraph)

- **Registers on `Zotero.Server.Endpoints`** — runs on the same HTTP server as Zotero's built-in API
- **JSON-RPC methods**: `item.search(terms)`, `item.attachments(citekey)`, `item.citationkey(keys)`, `item.export(keys, translator)`, `collection.scanAUX(collection, aux)`
- **No direct SQL** — all access through `Zotero.Items.getAsync()` etc.
- **Debug bridge**: `/debug-bridge/execute?password=...` executes arbitrary JS in Zotero context

---

## 4. Recommended Integration Architecture

### 4.1 Data Flow

```
hfpclawer 搜索到新论文 (arXiv / HF / OpenReview)
       │
       │ WRITE: POST /connector/saveItems (模拟浏览器插件)
       ▼
┌─────────────────────────────────────┐
│      Zotero Desktop (localhost:23119)             │
│  ├─ /connector/saveItems  ← hfpclawer POST      │
│  │   → ItemSaver.ATTACHMENT_MODE_IGNORE         │
│  │   → 创建条目 + 打 hfpclawer 标签             │
│  │   → 同步到 Zotero WebDAV / 云端               │
│  └─────────────────────────────────────┘
       │
       │ READ: pyzotero local=True → /api/users/0/items
       ▼
┌─────────────────────────────────────┐
│      hfpclawer                      │
│  ┌──────────────────────────────┐   │
│  │ zotero search / list / get   │   │
│  │ zotero push (-> connector)   │   │
│  │ zotero audit (延迟验证)       │   │
│  └──────────┬───────────────────┘   │
│             │                        │
│  ┌──────────▼───────────────────┐   │
│  │ paper_store (主论文DB)       │   │
│  │ + zotero_key / zotero_tag   │   │
│  └──────────────────────────────┘   │
└─────────────────────────────────────┘
       │
       │ ASYNC: 用户浏览器 Connector 后续抓取 PDF
       ▼
  用户打开 URL → Zotero Connector 浏览器插件
       → 检测 translator → 抓取 PDF
       → POST /connector/saveAttachment
       → Zotero 关联 PDF 到已有条目
```

### 4.2 写路径详解：模拟 Connector 协议

**不需要 API Key，不需要互联网，不需要浏览器插件**。hfpclawer 直接 POST 到 Zotero 桌面端：

| 端点 | 方法 | 用途 |
|:-----|:------|:------|
| `/connector/saveItems` | POST | 保存条目元数据（不含PDF附件） |
| `/connector/saveSingleFile` | POST | 保存网页快照/PDF（后续扩展） |
| `/connector/getRecognizedItem` | POST | 查询已保存条目的key |

**saveItems 完整请求格式**（从 Zotero 测试代码提取）:
```json
{
  "sessionID": "唯一会话ID",
  "uri": "来源URL",
  "items": [{
    "itemType": "journalArticle",
    "title": "...",
    "creators": [{"firstName": "...", "lastName": "...", "creatorType": "author"}],
    "tags": [{"tag": "hfpclawer", "type": 1}],
    "DOI": "10.xxx/xxxx",
    "url": "https://arxiv.org/abs/...",
    "date": "2025",
    "publicationTitle": "...",
    "abstractNote": "...",
    "extra": "hfpclawer_id: <sf_id>",
    "notes": [],
    "attachments": []
  }]
}
```

保存成功后：
- Zotero 创建条目（含 `hfpclawer` 标签）
- 附件模式=IGNORE（不下载PDF）
- 条目通过 Zotero WebDAV/云端同步到用户所有设备

### 4.3 标签策略

| 标签 | 来源 | 用途 |
|:-----|:------|:------|
| `hfpclawer` | hfpclawer 写操作 | 标识 hfpclawer 创建的条目 |
| `hfpclawer:auto` | hfpclawer cron | 自动导入的条目 |
| `hfpclawer:{domain}` | hfpclawer cron | 来源领域标记 (coc/gsnv/pde) |
| 用户已有标签 | 用户/Zotero | 不变 — hfpclawer 不删除 |

**筛选**: `/api/users/0/items?tag=hfpclawer`（local API 直接支持）

---

## 5. Proposed CLI Commands

```bash
# READ
hfpclawer zotero search --tag hfpclawer --q "neural operator"
hfpclawer zotero list --limit 50
hfpclawer zotero get ABC123 [--pdf /tmp/]
hfpclawer zotero tags                    # List all tags in library

# WRITE
hfpclawer zotero push [--aid 2501.01934]  # Push from paper_store to Zotero
hfpclawer zotero push --all              # Push all un-synced papers
hfpclawer zotero tag ABC123 --add hfpclawer --add cron:coc
hfpclawer zotero tag ABC123 --remove temp

# CRON / SYNC
hfpclawer zotero sync                     # Bidirectional sync
hfpclawer zotero config                   # Show config status
```

---

## 6. Implementation Phases

### Phase 1: READ (Estimated: 3-5 days)
- [ ] Add `pyzotero` dependency (optional extra: `pip install hfpclawer[zotero]`)
- [ ] Create `hfpclawer/zotero/` package with `client.py` (wraps pyzotero local)
- [ ] Implement `hfpclawer zotero search` — search local Zotero library
- [ ] Implement `hfpclawer zotero list` — list items
- [ ] Implement `hfpclawer zotero get` — get item detail + PDF attachment
- [ ] Implement `hfpclawer zotero tags` — list all tags
- [ ] Integration: paper_store `ensure_paper()` checks Zotero first (avoid duplicates)

### Phase 2: WRITE (Estimated: 3-5 days)
- [ ] Add pyzotero remote mode config (API key + user ID)
- [ ] Implement `hfpclawer zotero push` — from paper_store → Zotero
- [ ] Tag management (`hfpclawer` tag + source tags)
- [ ] PDF attachment upload via `attachment_simple()`
- [ ] Collection management (create/assign)

### Phase 3: CRON & SYNC (Estimated: 2-3 days)
- [ ] `hfpclawer zotero sync` — bidirectional sync with conflict detection
- [ ] Cron integration: `hfpclawer cron run` → also checks Zotero for new items
- [ ] WebDAV mount support for file access

---

## 7. Key Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Read API | pyzotero local=True + fallback SQLite RO | pyzotero for structured queries; SQLite for bulk path resolution |
| Write API | pyzotero remote=True (api.zotero.org) | Official, no plugin, internet required only during write |
| PDF access | SQLite → storage path → local filesystem | Fastest, no HTTP overhead |
| Config storage | `~/.hfpclawer/zotero.yaml` | Consistent with hfpclawer cron config pattern |
| MCP integration | Use pyzotero's built-in MCP server (or build hfpclawer-zotero MCP) | pyzotero MCP is read-only; hfpclawer may need write MCP |
| Dependency | Optional extra: `pip install hfpclawer[zotero]` | Don't force pyzotero on all users |
| Tag prefix | All hfpclawer tags use `hfpclawer:` prefix | Namespace separation from user's tags |

---

## 8. Open Questions for User Review

1. **API Key**: Do you have a Zotero API key ready, or should we guide you through creating one?
2. **Zotero Version**: Are you on Zotero 7+ (required for local HTTP API)? Zotero 9.0.5 is latest.
3. **WebDAV**: Do you have WebDAV configured for Zotero file sync, or is local filesystem sufficient?
4. **Phase Priority**: Should we start with Phase 1 (READ) first, or Phase 2 (WRITE)? (Recommended: READ first — unblocks paper_store dedup against your 5-year library.)
5. **SQLite RO vs pyzotero**: For bulk reads, ZotPilot's SQLite RO direct access is faster. Is that acceptable risk, or prefer pure pyzotero?
6. **Existing papers**: Should the first sync import all your existing Zotero papers into paper_store (tagged as `hfpclawer:synced`), or start fresh?
