# hfpclawer 集成改进计划

## 1. 审计增强（Audit System）

### Problem
- `download_state` 表为空（数据库被重建过）
- `arxiv_meta` 表无 source 列区分数据来源
- 无文件级别校验和审计
- Kaggle 数据未导入 SQLite

### Solution

#### A. 给 `arxiv_meta` 表加 `source` 列
- 加 `source TEXT DEFAULT ''` 列区分 `oai` / `kaggle`
- 迁移旧数据：OAI 导入的标记为 `oai`
- OAI 下载器 insert 时加 `source='oai'`
- Kaggle 下载器 insert 时加 `source='kaggle'`

#### B. 修复 `download_state` 写入
- `download_state` 表为空的原因调查 → DB 文件被覆盖重建
- 加 `file_sha256` 列到 `arxiv_meta` 表记录原始 JSONL 文件的 SHA256
- 新增 JSON 文件作为 download_state 的 fallback 持久化（已有 `oai_download_state.json` 模式，扩展到 Kaggle 也使用）
- 修复 `mark_done()` 不生效的问题：检查是否 DB 路径不一致

#### C. 新增 `hfpclawer audit` 命令
功能：
```
hfpclawer audit         → 数据源审计报告
hfpclawer audit --json  → JSON 格式输出
hfpclawer audit --check → 完整性校验（检查 OAI 日期范围、Kaggle 文件存在性）
```

审计报告内容：
- 各来源论文数（arxiv_meta.source）
- 各来源最新下载时间
- 数据完整性校验
- checksum / 文件指纹对比

### 实现计划
```
Phase A: schema 迁移 + 写入修复
  A1. 给 arxiv_meta 加 source 列（ALTER TABLE）
  A2. 给 OAI 插入加 source='oai'
  A3. 给 download_state 加 JSON fallback

Phase B: Kaggle 集成
  B1. kaggle.py 插入数据到 arxiv_meta（JSONL 解析 + INSERT）
  B2. kaggle.py 完成时写入 download_state
  B3. kaggle.py 加 source='kaggle'

Phase C: audit 命令
  C1. 新建 audit.py 模块
  C2. CLI 注册 hfpclawer audit 子命令
  C3. 测试
```

## 2. OpenCode A2A 集成优化

### 当前状态
- `opencode serve` 运行在端口 4096（auth: opencode/lab123456）
- `opencode-ai` pip 包（0.1.0-alpha.36）已安装可导入
- SDK 的 `session.chat()` 可用，用 dict 代替 Part 避开 bug
- **Serve API 不支持切换 cwd** — 项目目录固定为启动时的 cwd（目前 PDEBench）
- Python SDK 只有一个 base_url，不支持切换后端场景
- A2A 层级子代理：Hermes → OpenCode A2A Server → OpenCode 实例

### 优化方案

#### A. opencode skill 更新
更新 `opencode` 技能，补充 SDKA2A 章节：

```markdown
## A2A (Agent-to-Agent) Integration

OpenCode Server supports A2A via the opencode-ai Python SDK.

### Setup
```bash
pip install opencode-ai
```

### Basic Usage
```python
import base64
from opencode_ai import Opencode

auth = base64.b64encode(b"USER:PASS").decode()
client = Opencode(
    base_url="http://localhost:PORT",
    default_headers={"Authorization": f"Basic {auth}"},
)

# Create session
sid = client.post("/session", body={}).json()["id"]

# Chat
resp = client.session.chat(
    id=sid,
    model_id="deepseek-chat",
    provider_id="302ai",
    parts=[{"type": "text", "text": "Do X"}],  # dict, NOT Part!
    timeout=120,
)

# Extract text reply
for p in resp.parts:
    if getattr(p, 'type', '') == 'text':
        print(getattr(p, 'text', ''))
```

### ⚠️ IMPORTANT: Project Switching Problem
OpenCode Serve **does NOT support per-session cwd**.
- `POST /session` accepts `{"cwd": "..."}` in JSON body but this field is **NOT persisted** to the session object
- Session always inherits the serve process's cwd (where `opencode serve` was started)
- There is NO API to change `directory` after session creation

**Workarounds:**
1. **Restart serve in target dir**: `pkill -f "opencode serve" && cd /target && opencode serve`
2. **Use `cd` in prompt + `delegate_task` with per-task ACP** (Hermes native subagent)
3. **Run opencode as ACP subagent** with per-child workdir (preferred):
   ```python
   delegate_task(
       goal="Implement X in project Y",
       toolsets=["terminal", "file"],
       workdir="/path/to/project",  # ← Hermes handles this
   )
   ```
4. **Multiple serve instances on different ports** (one per project)

**Note:** If you need A2A across projects, restarting serve is the cleanest approach.

### Known Pitfalls
- `session.create()` with empty body may 400 → use `client.post("/session", body={})`
- `Part` is a `Union` type, NOT instantiable → use dict `{"type": "text", "text": "..."}`
- `session.init()` requires real `message_id` (starting with `msg_`) — cannot use placeholder
- No OpenAPI spec available in serve mode (only in web mode)
```

#### B. Command switch project
新增 Hermes 命令 `opencode switch-project <path>`：

```python
def opencode_switch_project(project_dir: str):
    """Restart opencode serve in a different project directory"""
    # 1. Gracefully stop current serve
    subprocess.run(["pkill", "-f", "opencode serve"], timeout=5)
    time.sleep(1)
    # 2. Start serve in new dir
    subprocess.Popen(
        ["opencode", "serve", "--port", "4096"],
        cwd=os.path.expanduser(project_dir),
    )
    # 3. Wait for health
    for i in range(10):
        try:
            r = httpx.get("http://localhost:4096/global/health", auth=...)
            if r.status_code == 200:
                return {"status": "ok", "project": project_dir}
        except:
            time.sleep(1)
    return {"status": "timeout", "project": project_dir}
```

**但由于 Hermes 目前没有 tool 可以注册 switch-project 命令**，我们先更新 opencode skill，把这个逻辑写在 skill 里，Hermes 需要切换项目时按技能步骤执行。

#### C. 多 serve 实例方案
如果项目切换频繁，可以跑多个 serve 实例在不同端口：

| 项目 | 端口 | 用途 |
|------|------|------|
| PDEBench | 4096 | 主要项目 |
| hfpapers-crawler | 4097 | 爬虫项目 |
| arxiv-metadata-service | 4098 | 元数据服务 |

每个实例用 systemd/user unit 管理或 tmux 会话。

## 3. OpenCode Skill 更新

当前 skill 的 Serve Mode 章节已过期（写了很多错误的 SDK 用法）。
需要整体更新为正确的 SDK/A2A 用法。

### 改动清单
1. `Serve Mode` → 重写为 `A2A Integration`
2. 删除错误的 SDK 示例（如 `Part(type="text")`）
3. 添加 `opencode-ai` pip 安装步骤
4. 添加切换项目工作区的方法
5. 保留 `curl` 快速参考
6. 所有 `execute_code` 示例改为 SDK + raw HTTP

## 优先级

1. **高**: 审计系统（Phase A: schema 迁移 + 修复写入）
2. **高**: OpenCode skill 更新（修正过时内容）
3. **中**: 审计系统（Phase B: Kaggle 集成）
4. **中**: OpenCode 项目切换方案
5. **低**: 审计系统（Phase C: audit 命令）
6. **低**: 多 serve 实例管理

## 时间估算
- Phase A: ~30min
- Phase B: ~20min
- Phase C: ~25min
- Skill 更新: ~15min
- 总计: ~90min
