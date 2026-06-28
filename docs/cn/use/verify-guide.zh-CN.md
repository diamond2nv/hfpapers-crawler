# hfpclawer verify 模块 — 用户指南

## 概述

`hfpclawer.verify` 模块实现了 **5 层公式验证管线**：

| 层级 | 引擎 | 依赖 | 零配置？ | 功能 |
|:-----|:-----|:-----|:---------|:-----|
| **L1** | SymPy | `sympy`（pip） | ✅ 是 | 符号推导 & 代数等价性验证 |
| **L2** | numpy | `numpy`（pip） | ✅ 是 | 随机参数采样的数值交叉检验 |
| **L3** | pint | `pint`（pip） | ✅ 是 | 物理量纲分析 |
| **L4** | 纯 Python | — | ✅ 是 | 物理极限测试（远场、近场、对称性） |
| **L5** | SymPy | `sympy`（pip） | ✅ 是 | 奇异点检测（分母为零、分支切割） |

**关键设计决策：**
- L1–L3 层**完全独立**（不同工具链，同一公式）
- L4 和 L5 依赖 **SymPy**（与 L1 同一引擎，不同分析角度）
- **无需外部 API 调用**——所有验证在本地执行
- **优雅降级**：缺少 `sympy` → L1/L5 跳过；缺少 `pint` → L3 跳过。永不崩溃。

## 快速开始

```python
from hfpclawer.verify.registry import FormulaEntry, FormulaRegistry
from hfpclawer.verify.pipeline import VerificationPipeline

# 1. 创建注册表
reg = FormulaRegistry("my_formulas.jsonl")

# 2. 添加公式
entry = FormulaEntry(
    fid="eq:biot-savart-segment",
    latex=r"B = \frac{\mu_0 I}{4\pi d} (\cos\alpha_2 - \cos\alpha_1) \hat{\phi}",
    sympy="mu0*I/(4*pi*d)*(cos(alpha2)-cos(alpha1))",
    pint_dimension="magnetic flux density",
    source_keys=["Griffiths2023"],
    tags=["magnetostatics", "biot-savart"],
)
reg.add(entry)
reg.save()

# 3. 验证
pipe = VerificationPipeline(registry=reg)
results = pipe.run_all()  # 对所有未验证条目执行 L1→L5
pipe.save_results("verify-results.json")
```

## 安装

verify 模块作为 `hfpclawer` 的一部分安装：

```bash
# 最小安装——无需额外依赖
pip install hfpclawer

# 带 verify 依赖（推荐）
pip install "hfpclawer[verify]"   # 添加 sympy, pint, numpy

# 或从源码安装
cd hfpapers-crawler
pip install -e ".[verify]"
```

### 依赖检查

```python
import hfpclawer.verify as v
print(v.check_available())
# 返回字典：{"sympy": True, "pint": True, "numpy": True}
```

## Formula 注册表（JSONL 后端）

### Schema

```json
{
  "registry_schema_version": 1,
  "fid": "eq:biot-savart-segment",
  "latex": "B = \\frac{\\mu_0 I}{4\\pi d} (\\cos\\alpha_2 - \\cos\\alpha_1) \\hat{\\phi}",
  "sympy": "mu0*I/(4*pi*d)*(cos(alpha2)-cos(alpha1))",
  "source_keys": ["Griffiths2023"],
  "extracted_from": "sf:2501.01934",
  "equation_index": 15,
  "pint_dimension": "magnetic flux density",
  "verification_status": "unverified",
  "verified_at": null,
  "expires_at": null,
  "verifications": [],
  "tags": ["magnetostatics", "biot-savart"]
}
```

### 字段说明

| 字段 | 必需 | 说明 |
|:-----|:-----|:-----|
| `fid` | ✅ | 唯一公式 ID（如 `eq:biot-savart-segment`） |
| `latex` | ✅ | LaTeX 表示（规范交换格式） |
| `sympy` | ❌ | SymPy 表达式字符串（L1、L5 需要） |
| `source_keys` | ❌ | 引用键（如 `["Griffiths2023"]`） |
| `extracted_from` | ❌ | 来源论文的 `sf_id` |
| `equation_index` | ❌ | 来源论文中的公式编号 |
| `pint_dimension` | ❌ | 物理维度键（见 `dimensional.py`） |
| `tags` | ❌ | 分类标签，用于查询 |

### 支持的维度键

| 键 | 单位 | 物理量 |
|:---|:-----|:-------|
| `magnetic flux density` | T | 磁通密度（特斯拉） |
| `magnetic field strength` | A/m | 磁场强度 |
| `length` | m | 长度 |
| `temperature` | K | 温度 |
| `frequency` | Hz | 频率 |
| `electric current` | A | 电流 |
| `electric potential` | V | 电势 |
| `energy` | J | 能量 |
| `force` | N | 力 |
| `pressure` | Pa | 压强 |
| `velocity` | m/s | 速度 |
| `acceleration` | m/s² | 加速度 |
| `area` | m² | 面积 |
| `volume` | m³ | 体积 |
| `dimensionless` | — | 无量纲数 |

### TTL（有效期）

已验证的公式默认在 **365 天**后过期。修改方式：

```python
from hfpclawer.verify.registry import FormulaRegistry, DEFAULT_EXPIRY_DAYS

# 逐条覆盖
entry.mark_verified("L1", "passed", ttl_days=180)  # 6个月

# 修改全局默认值
# hfpclawer/verify/registry.py: DEFAULT_EXPIRY_DAYS = 365
```

## 编程 API

### 运行单层

```python
from hfpclawer.verify.registry import FormulaRegistry
from hfpclawer.verify.pipeline import VerificationPipeline

reg = FormulaRegistry("my_formulas.jsonl")
pipe = VerificationPipeline(registry=reg)

entry = reg.get("eq:biot-savart-segment")

# 运行特定层
result_l1 = pipe.run_l1(entry)   # SymPy 符号
result_l3 = pipe.run_l3(entry)   # pint 量纲

# 或全部
all_results = pipe.verify_entry(entry)
```

### 层结果结构

```python
@dataclass
class LayerResult:
    fid: str          # 公式 ID
    layer: str        # "L1"|"L2"|"L3"|"L4"|"L5"
    passed: bool      # 通过/失败
    detail: str       # 人类可读的说明
    computed: float | None  # L2 数值计算值
    expected: float | None  # L2 期望值
    rel_error: float | None # L2 相对误差
```

### 注册表查询

```python
# 所有公式
all_entries = reg.load_all()

# 按状态
unverified = reg.get_by_status("unverified")
verified = reg.get_by_status("verified")
failed = reg.get_by_status("failed")

# 按标签
magnetostatic = reg.get_by_tag("magnetostatics")

# 按来源论文
from_paper = reg.get_by_source("sf:2501.01934")

# 仅已过期
expired = reg.get_expired()

# 统计
stats = reg.stats()
# {"total": 42, "by_status": {"verified": 30, "unverified": 8, "failed": 4}, ...}
```

## CLI 使用（未来）

verify 的 CLI 命令计划在后续版本添加。当前请使用 Python 脚本：

```bash
# 验证所有未注册公式
python -c "
from hfpclawer.verify.pipeline import VerificationPipeline
from hfpclawer.verify.registry import FormulaRegistry
pipe = VerificationPipeline(registry_path='formula_registry.jsonl')
results = pipe.run_all()
print(f'通过: {sum(1 for r in results if r.passed)}/{len(results)}')
"
```

---

# 可选第三方服务

以下服务**非基本使用所需**。它们为需要最高级别公式验证可信度的用户提供额外的交叉验证。

---

## Wolfram Engine（Docker/Podman）

**用途：** L1 交叉验证——使用第二个计算机代数系统（CAS）独立验证 SymPy 结果。

**状态：** 🟢 已在外部仓库（`gsnv-theory`、`coc-inverse-agent`）中实现。尚未集成到 `hfpclawer.verify` 核心。计划 v0.8.x 集成。

### 方案 A：容器（推荐）

#### 1. 获取许可证

1. 访问 https://www.wolfram.com/engine/free-license/
2. 创建免费的 Wolfram ID（需要邮箱）
3. 免费许可证密钥立即通过邮件发送给您
4. 许可条款：个人/开发用途免费；每年续期一次

> **实践日期：** 2026-03-15 —— 通过 wolfram.com/engine 获取免费许可证。已验证：许可证密钥无需账户验证即可在终端使用。许可证续期邮件在到期前约 30 天发送。

#### 2. 拉取并运行容器

```bash
# 拉取官方镜像
docker pull wolframresearch/wolfram-engine:15.0.0

# 或通过 podman
podman pull docker.io/wolframresearch/wolfram-engine:15.0.0

# 运行并激活许可证
docker run -it --rm -e WOLFRAM_LICENSE_KEY="xxxx-xxxx-xxxx-xxxx" \
  wolframresearch/wolfram-engine:15.0.0 wolframscript -code "Print[1+1]"
```

**故障排除：**
- 首次运行时，容器可能要求输入 Wolfram ID 密码。预认证方法：
  ```bash
  docker run -it --rm wolframresearch/wolfram-engine:15.0.0 wolframscript -activate
  # 按提示输入 Wolfram ID 邮箱 + 密码（不仅仅是许可证密钥）
  ```
- 激活状态存储在容器中；要持久保存，请挂载卷：
  ```bash
  docker run -it --rm -v ~/.WolframEngine:/root/.WolframEngine \
    wolframresearch/wolfram-engine:15.0.0 wolframscript -code "..."
  ```

#### 3. 验证安装

```bash
# 简单测试
docker exec wolfram-engine wolframscript -code \
  'Print[TeXForm[Integrate[1/(x^2+z^2)^(3/2), {z, -Infinity, Infinity}]]]'
# 预期输出：\frac{2}{x^2}

# 与 SymPy 交叉验证
python -c "import sympy as sp; x=sp.symbols('x',positive=True); \
  print(sp.latex(sp.integrate(1/(x**2+z**2)**(3/2), (z, -sp.oo, sp.oo))))"
# 预期输出：\frac{2}{x^{2}}
```

> **实践日期：** 2026-05-20 —— Docker Wolfram Engine 15.0.0 在 Ubuntu 22.04（i5-12450H）上验证。内存占用：空闲 ~800 MB，符号积分时 ~1.5 GB。冷启动：约 8 秒。

### 方案 B：本地安装（Linux）

```bash
# 1. 下载 Wolfram Engine 安装程序
wget https://account.wolfram.com/download/public/wolfram-engine/15.0.0/engine/WolframEngine_15.0.0_LINUX.sh

# 2. 运行安装程序（需要约 2 GB 磁盘空间）
chmod +x WolframEngine_15.0.0_LINUX.sh
sudo ./WolframEngine_15.0.0_LINUX.sh

# 3. 激活
wolframscript -activate

# 4. 测试
wolframscript -code 'Print[TeXForm[D[Sin[x]^2, x]]]'
# 预期输出：2 \sin (x) \cos (x)
```

> **实践日期：** 2026-04-10 —— 在 Ubuntu 22.04 上本地安装 Wolfram Engine 15.0.0。即使使用 `--nox11` 标志，安装程序也会显示 GUI 向导——Docker 方式更简单。

### 在 hfpclawer 中的配置

```python
# 未来 config.yaml 配置段（计划 v0.8.x）
verify:
  wolfram:
    method: docker          # "docker" | "podman" | "native" | "disabled"
    container: wolfram-engine
    timeout: 30             # 秒
```

## Wolfram Alpha API

**用途：** L1 回退——用于 SymPy 和 Wolfram Engine 都无法原生处理的表达式（如特殊函数、新形式的不定积分）。

**状态：** 🟡 尚未在 `hfpclawer.verify` 中实现。计划 v0.8.x 作为可选的 L1b 回退。

### 1. 获取 API 密钥

1. 在 https://products.wolframalpha.com/api/ 注册
2. 点击 "Get Started" → "Sign Up for Free"
3. 创建 Wolfram ID（与 Engine 同一账号）
4. 选择 **免费计划**（每月 2,000 次 API 调用）
5. 您的 App ID（API 密钥）立即显示在控制台中

> **实践日期：** 2026-03-20 —— 在 wolframalpha.com 获取免费版 App ID。API 端点：`https://api.wolframalpha.com/v2/query`。已确认：每月 2,000 次查询硬上限；按月重置。3 个月后未观察到 API 密钥过期。

### 2. 速率限制

| 计划 | 月限制 | 速率限制 | 延迟 | 使用场景 |
|:-----|:-------|:---------|:-----|:---------|
| 🆓 免费 | 2,000 | ~1 req/s | ~2-5s | 开发、抽查验证 |
| 💼 专业版（$60/年） | 10,000 | ~5 req/s | ~1-3s | 活跃研究 |
| 🏢 企业版 | 自定义 | 自定义 | <1s | 生产管线 |

### 3. Python 客户端

```bash
pip install wolframalpha
```

```python
import wolframalpha
import os

# 从 .env 或环境变量读取
client = wolframalpha.Client(os.environ["WOLFRAM_ALPHA_APP_ID"])

# 查询
res = client.query("integrate 1/(x^2+z^2)^(3/2) dz from -inf to inf")

# 解析结果
for pod in res.pods:
    if pod.title == "Indefinite integral":
        print(pod.text)
        # → (2 z)/(x^2 Sqrt[x^2+z^2])
```

### 4. 速率限制处理

```python
import time
import wolframalpha
from functools import lru_cache

class WolframAlphaClient:
    def __init__(self, app_id: str, monthly_budget: int = 2000):
        self.client = wolframalpha.Client(app_id)
        self.call_count = 0
        self.monthly_budget = monthly_budget
        self.last_call = 0.0
    
    @lru_cache(maxsize=128)
    def query(self, query_str: str) -> str | None:
        """带速率限制的 Alpha 查询，设有月度预算。"""
        if self.call_count >= self.monthly_budget:
            logger.warning("Alpha API 预算已耗尽（%d/月）", self.monthly_budget)
            return None
        
        # 速率限制：1 req/s
        elapsed = time.time() - self.last_call
        if elapsed < 1.0:
            time.sleep(1.0 - elapsed)
        
        try:
            res = self.client.query(query_str)
            self.call_count += 1
            self.last_call = time.time()
            return extract_result(res)
        except Exception as exc:
            logger.error("Alpha API 错误：%s", exc)
            return None
```

### 5. 在 hfpclawer 中的配置

```python
# 未来 config.yaml 配置段
verify:
  wolfram_alpha:
    enabled: false           # 默认禁用
    app_id_env: "WOLFRAM_ALPHA_APP_ID"
    monthly_budget: 500      # 保守使用——仅用于边界情况
```

## Lean 4（未来 L6）

**用途：** 作为最高验证层的形式定理证明。

**状态：** 🔴 未实现。保留为未来主要版本的 L6。

**文档：** 详见 `docs/formula-cross-validation-architecture.md` §10 的 Lean 4 设计。

## 成本汇总

| 服务 | 成本 | 限制 | 用途 |
|:-----|:-----|:-----|:-----|
| SymPy（L1、L5） | 🆓 免费 | 无限制 | 符号推导 |
| numpy（L2） | 🆓 免费 | 无限制 | 数值交叉检验 |
| pint（L3） | 🆓 免费 | 无限制 | 量纲分析 |
| Wolfram Engine（Docker） | 🆓 免费* | 1年许可证 | CAS 交叉验证 |
| Wolfram Alpha API | 🆓 免费（2K/月） | 2,000/月 | 最终交叉验证 |
| Lean 4 | 🆓 免费 | 无限制 | 形式化证明（未来） |

*Wolfram Engine 免费许可证：仅限个人/开发用途，每年续期。

## 与替代 CAS 的对比

| 引擎 | 安装 | 速度 | 覆盖范围 | 许可证 |
|:-----|:-----|:-----|:---------|:-------|
| SymPy | `pip install sympy`（即时） | 快 | 基础函数良好 | BSD（开源） |
| Wolfram Engine | Docker ~2 GB 拉取 | 中等 | 优秀（特殊函数、微分方程） | 专有（免费个人） |
| Wolfram Alpha | 仅 API | 慢（2-5s） | 最佳（逐步推导） | 专有（免费层） |
| SageMath | `apt install sagemath` ~4 GB | 启动慢 | 良好（封装 SymPy + Maxima + Singular） | GPL（开源） |
| Maxima | `apt install maxima` ~200 MB | 中等 | 符号类良好 | GPL（开源） |

**推荐：** 从 L1-SymPy 开始。如果您遇到 SymPy 无法处理的表达式（例如涉及特殊函数的积分如 `HypergeometricPFQ`，或 SymPy 返回未求值的分段积分），再添加 Wolfram Engine。

## 常见问题（FAQ）

### 问：使用 verify 模块需要任何 API 密钥吗？

**不需要。** verify 模块完全离线运行，无需外部 API 调用。只有 L3 交叉验证（Wolfram）需要 API 密钥或 Docker——而且它完全是可选的。

### 问：我的公式是敏感/专有的。我能离线验证吗？

**可以。** 所有 L1–L5 层都在本地运行。没有任何数据离开您的计算机。

### 问：哪一层能捕获单位转换错误（μm → m）？

**L3（pint）** 捕获量纲不匹配。**L4（极限测试）** 通过检查结果是否落在物理合理范围内，捕获数值量级错误。

### 问：如何验证没有 SymPy 表达式的公式？

L1 和 L5 会优雅跳过。如果您提供 `pint_dimension`，L3（pint 量纲分析）仍然有效。L2 数值检查仍然可以通过手写 Python 代码运行。

### 问：如果 sympy 或 pint 未安装会发生什么？

优雅降级——缺失的引擎会记录警告并跳过。管线永远不会因缺少可选依赖而崩溃。
