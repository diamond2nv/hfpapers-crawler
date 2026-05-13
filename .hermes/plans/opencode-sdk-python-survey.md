# OpenCode Python SDK 调研报告

## 仓库信息

| 属性 | 值 |
|------|-----|
| 仓库 | [anomalyco/opencode-sdk-python](https://github.com/anomalyco/opencode-sdk-python) |
| PyPI | `opencode-ai` |
| Python | ≥3.8 |
| 生成方式 | Stainless（从 OpenAPI spec 自动生成） |
| HTTP 客户端 | httpx（同步） + httpx/aiohttp（异步） |
| License | MIT 隐含 |
| 状态 | 106 commits，有 release-please 自动化发布 |

## 安装

```bash
pip install opencode-ai
```

## 核心 API 方法

### Session 管理

```python
from opencode_ai import Opencode

client = Opencode(base_url="http://localhost:4096",
                  default_headers={"Authorization": f"Basic {base64_auth}"})

# 创建 session
session = client.session.create()  # POST /session → Session(id, slug, ...)

# 列出 sessions
sessions = client.session.list()   # GET /session → SessionListResponse

# 删除 session
client.session.delete(id)          # DELETE /session/{id}

# 中止 session
client.session.abort(id)           # POST /session/{id}/abort
```

### 发送消息（核心功能）

```python
from opencode_ai.types.session_chat_params import Part

resp = client.session.chat(
    id=session_id,
    model_id="deepseek-chat",
    provider_id="302ai",
    parts=[Part(type="user", text="Your prompt here")],
    system="Optional system prompt",       # ← 可选
    tools={"tool_name": True},              # ← 可选，控制可用工具
)
# 返回 AssistantMessage(id, cost, tokens, provider_id, modelID, ...)
# 可通过 resp 获取 AI 响应内容
```

**⚠️ 已知问题：** `Part` 是 `Union[TextPartInputParam, FilePartInputParam]` 的 **TypeAlias**，不能 `Part(...)` 直接实例化。要用字典代替：

```python
# ✅ 正确方式（用字典而不是 Part()）
client.session.chat(
    id=sid,
    model_id="deepseek-chat",
    provider_id="302ai",
    parts=[{"type": "user", "text": "Hello"}],
)
```

### 获取消息历史

```python
msgs = client.session.messages(id)  # GET /session/{id}/message
# 返回 List[SessionMessagesResponseItem]
# 每个 item: {info: Message, parts: List[Part]}
```

### 其他方法

```python
# App
client.app.get()        # 获取 app 信息
client.app.init()       # 分析并生成 AGENTS.md
client.app.providers()  # 列出所有 providers

# Config
client.config.get()        # 获取当前配置
client.config.providers()  # 获取所有 provider 列表

# Files
client.file.read(params)  # 读取文件
client.file.status()      # 文件状态

# Find
client.find.text(params)  # 搜索文本
client.find.files(params) # 搜索文件

# Share / Revert
client.session.share(id)
client.session.revert(id, message_id=..., part_id=...)
client.session.summarize(id, model_id=..., provider_id=...)
```

## 关键类型

### TextPartInputParam（user message）
```python
class TextPartInputParam(TypedDict, total=False):
    text: Required[str]
    type: Required[Literal["text"]]   # "text"
    id: str                           # optional
    synthetic: bool                   # optional
    time: {start: float, end?: float}  # optional
```

### FilePartInputParam（附文件）
```python
class FilePartInputParam(TypedDict, total=False):
    mime: Required[str]               # "application/pdf" etc
    type: Required[Literal["file"]]   # "file"
    url: Required[str]                # file:///path or http://
    id: str
    filename: str
    source: FilePartSourceParam
```

### AssistantMessage（返回）
```python
class AssistantMessage(BaseModel):
    id: str
    cost: float
    mode: str
    api_model_id: str                  # alias: modelID
    path: {cwd: str, root: str}
    provider_id: str
    role: Literal["assistant"]
    session_id: str
    system: List[str]
    time: {created: float, completed?: float}
    tokens: {input: float, output: float, reasoning: float, cache: {read, write}}
    error: Optional[Error]
    summary: Optional[bool]
```

## 注意事项 / PITFALLS

### 1. `Part` 不能直接实例化
```python
from opencode_ai.types.session_chat_params import Part
# ❌ TypeError: Cannot instantiate typing.Union
part = Part(type="text", text="hello")
# ✅ 用字典
part = {"type": "text", "text": "hello"}
```

### 2. Base URL 和 Auth 需手动配置
SDK 默认无 base_url 和 auth，需手动传：
```python
import base64
client = Opencode(
    base_url="http://localhost:4096",
    default_headers={
        "Authorization": f"Basic {base64.b64encode(b'opencode:lab123456').decode()}"
    },
)
```

### 3. `session.create()` 空 body 可能 400
```python
# ❌ 可能报错
client.session.create()
# ✅ 用 raw POST 绕过
client.post("/session", body={})
```

### 4. `client.session.chat()` 是同步阻塞的
会等待 AI 完全响应才返回。对长时间任务（代码生成、分析等），考虑用超时或异步。

### 5. 异步客户端
```python
from opencode_ai import AsyncOpencode
client = AsyncOpencode(...)
resp = await client.session.chat(...)
```

### 6. 错误处理
所有异常继承 `opencode_ai.APIError`：
- `BadRequestError` (400)
- `AuthenticationError` (401)
- `RateLimitError` (429)
- `InternalServerError` (500)
- `APIConnectionError` (网络不通)

## 与 Hermes Agent 集成方案

```python
import base64
from opencode_ai import Opencode

def opencode_client():
    auth = base64.b64encode(b"opencode:lab123456").decode()
    return Opencode(
        base_url="http://localhost:4096",
        default_headers={"Authorization": f"Basic {auth}"},
        timeout=300.0,  # 5 分钟超时
    )

# 步骤 1: 创建 session
client = opencode_client()
session = client.session.create()

# 步骤 2: 发送消息
resp = client.session.chat(
    id=session.id,
    model_id="deepseek-chat",
    provider_id="302ai",
    parts=[{"type": "text", "text": "implement feature X"}],
)

# 步骤 3: 检查结果
print(f"Cost: ${resp.cost:.4f}, Tokens: {resp.tokens.input + resp.tokens.output}")

# 步骤 4: 获取完整消息历史
msgs = client.session.messages(session.id)

# 步骤 5: 清理
client.session.delete(session.id)
```

## 与 openeode-server 的 ACP 模式对比

| 维度 | SDK (HTTP API) | ACP (stdio) |
|------|---------------|-------------|
| 通信方式 | HTTP REST | JSON-RPC over stdio |
| 适用场景 | 自动化、脚本、后台 | 编辑器集成 |
| 状态 | 无状态（每次请求独立） | 有状态（子进程生命周期） |
| 并发 | 支持多 session 并发 | 单进程单会话 |
| 依赖 | `pip install opencode-ai` | 无额外依赖 |
| 复杂度 | 低 | 中 |
| 日志追踪 | 有 `tokens`, `cost` 字段 | 需要解析 stderr |

## 结论

Python SDK 适合以下场景：
1. **Hermes Agent 直接调用 OpenCode** — 创建 session → 发消息 → 获取结果
2. **定时任务** — cron 中自动调用 OpenCode 做代码生成
3. **批量代码分析** — 多 session 并发

对比 ACP 模式，SDK 更适合自动化集成场景，而 ACP 更适合编辑器内交互式使用。
