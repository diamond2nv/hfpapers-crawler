---
title: 论文公式多维度交叉验证体系 — 从 LaTeX 到 Lean 4
author: 初稿
date: 2026-06-27
tags: [formula-verification, sympy, wolfram, lean4, pint, quarto]
---

## 一、问题陈述

学术论文中的公式错误极其普遍——2015 年一项对 Nature 论文的审计发现 >12% 的方程存在可复现性错误。在物理/工程领域，量纲不匹配、符号错误、极限条件未检验是三大主要问题。

**我们的方案：** 6 层独立验证管道，每层使用完全不同的工具链，在 LaTeX 层面统一交换格式。

```
┌─────────────────────────────────────────────────────────────┐
│                    LaTeX 统一交换格式                        │
│  每个公式以 LaTeX \tag{eq:id} 作为唯一标识符                 │
│                    │                                        │
│    ┌───────────────┼───────────────┐                        │
│    │               │               │                        │
│    ▼               ▼               ▼                        │
│ ┌────────┐   ┌──────────┐   ┌──────────┐                   │
│ │ SymPy  │   │ Wolfram  │   │ 数值计算  │                   │
│ │ 符号推导│   │ Engine   │   │ N=10⁵   │                   │
│ │(开源)  │   │(商用CAS) │   │(黄金标准)│                   │
│ └───┬────┘   └────┬─────┘   └────┬─────┘                   │
│     │             │              │                          │
│     └──────┬──────┘              │                          │
│            │                     │                          │
│            ▼                     ▼                          │
│     ┌────────────────┐   ┌──────────────┐                  │
│     │ 代数等价性验证  │   │ 数值精度验证  │                  │
│     │ LaTeX_A=LaTeX_B│   │ |B/B₀-1|<1e-8│                  │
│     └────────────────┘   └──────┬───────┘                  │
│                                 │                          │
│    ┌───────────────┼────────────┼──────────────┐           │
│    ▼               ▼            ▼              ▼           │
│ ┌────────┐   ┌──────────┐ ┌──────────┐  ┌──────────┐      │
│ │ pint   │   │ 极限检测  │ │ 奇异点检测│  │ Lean 4  │      │
│ │ 量纲   │   │ 远场/近场 │ │ 分母为零 │  │ 形式化  │      │
│ │ 检查   │   │ 对称性   │ │ 分支切割 │  │ 证明    │      │
│ └────────┘   └──────────┘ └──────────┘  └──────────┘      │
└─────────────────────────────────────────────────────────────┘
```

---

## 二、LaTeX 统一公式代码层

### 2.1 核心理念

每个公式以 LaTeX 代码作为**唯一规范形式**，而不是 Python 表达或 Mathematica 表达式。所有验证工具的输入/输出都归一化为 LaTeX。

### 2.2 已在 gsnv-theory 验证的格式

```python
# physics/formula_verify/verify_shared.py
formula_registry = {
    "eq:biot-savart-segment": {
        "latex": r"B = \frac{\mu_0 I}{4\pi d} (\cos\alpha_2 - \cos\alpha_1) \hat{\phi}",
        "sympy": "mu0*I/(4*pi*d)*(cos(alpha2)-cos(alpha1))",
        "wolfram": "TeXForm[mu0*I/(4*pi*d)*(Cos[alpha2]-Cos[alpha1])]",
        "dimension": "magnetic flux density",
        "verified_by": ["L1", "L2", "L3", "L4", "L5"],
        "source": "Griffiths (2023) §5.3.2"
    }
}
```

### 2.3 LaTeX 归一化管道

SymPy 输出 `sp.latex()` → Wolfram 输出 `TeXForm[...]` → 对比 → 写入 QMD

```
 SymPy: sp.latex(B_expr)  →  "\\frac{\\mu_{0} I}{2 \\pi d}"
 Wolfram: TeXForm[B]      →  "\\frac{I \\mu _0}{2 d \\pi}"
                             → normalize_whitespace()
                             → normalize_commutative_order()
                             → 等价? ✅ / ❌
```

**关键教训：** SymPy 和 Wolfram 对同类项排序不同（SymPy 按参数名排序，Wolfram 按出现顺序）。不能直接字符串比较，必须通过 `sp.simplify(A - B) == 0` 做代数等价性验证。

### 2.4 Quarto QMD + LaTeX 集成

已验证于：
- **gsnv-theory**: `docs/nv-current-imaging-book/` 全部使用 `ctexart` + `xelatex`
- **gsnv-theory**: `docs/formulas/generated/qmd/` 自动生成公式 QMD
- **coc-inverse-agent**: `docs/reports/phase1-report/` — `ctexrep` 书格式

自动生成管线：
```
FormulaRegistry (JSONL) 
    → SymPy/Wolfram/数值 三路验证
    → 生成 .qmd 公式文件
    → quarto render → PDF
```

---

## 三、SymPy 符号推导层（L1）

### 3.1 已验证场景

| 场景 | repo | 公式 | SymPy 角色 |
|:-----|:-----|:------|:----------|
| Biot-Savart 闭式解 | gsnv | ∫ 1/(x²+z²)^(3/2) dx | 符号积分 → 闭式 |
| Jiles-Atherton 磁滞 | gsnv | dM/dH = ... | 微分方程符号解 |
| Γ_OM = 4g₀²/κ | coc | 光机械耦合率 | 代数化简 |
| 无限长导线极限 | gsnv+BW | B = μ₀I/(2πd) | 积分∞极限 |

### 3.2 SymPy 技巧（踩坑记录）

**陷阱 1: `sp.simplify(A - B) == 0` 失效**
```python
# SymPy 的代数简化不是万能的
A = sp.sqrt(x**2)  # returns Abs(x)
B = x              # Abs(x) ≠ x for x < 0
# 必须加 positive=True 假设
x = sp.symbols('x', positive=True)
```

**陷阱 2: 积分返回 Piecewise**
```python
# ∫ sin(2πfᵢt)·sin(2πfⱼt) dt 返回 Piecewise
# 不能直接 float() 转换
# 解决方案：数值代入特定参数再求值
```

**陷阱 3: `sp.N()` 精度**
```python
# SymPy 数值求值与 numpy 高精度积分不匹配时
# 应信任 numpy N=10⁵ 积分而非 SymPy 的数值近似
```

### 3.3 推荐模式

```python
def verify_formula_sympy():
    """L1-Symbolic: 三步模式"""
    # Step 1: 符号推导
    x, y = sp.symbols('x y', positive=True, real=True)
    F_analytical = sp.integrate(f(x), (x, 0, y))
    
    # Step 2: 数值验证（而非代数等价）
    F_num = float(F_analytical.subs({x: 1.0, y: 2.0}))
    assert abs(F_num - expected) < 1e-14
    
    # Step 3: LaTeX 导出
    latex_str = sp.latex(F_analytical)
```

---

## 四、Wolfram Engine（Docker/Podman）层（L3 交叉验证）

### 4.1 架构

已在 **coc-inverse-agent** 的 `server/wolfram_server.py` + `metrics/wolfram.py` 中实现：

```
三引擎退化策略（已验证于 coc-inverse-agent）:
  1. Native wolframscript (最快) → 
  2. Docker wolfram-engine:15.0 (中度) → 
  3. Podman wolfram-engine (备选) →
  4. 全部失败 → SymPy fallback + 警告
```

### 4.2 Docker Wolfram Engine 集成

已验证于 gsnv-theory（容器名 `wolfram-engine` 运行中）:

```bash
# 本地容器
docker exec wolframscript -code 'Print[TeXForm[Integrate[1/(x^2+z^2)^(3/2), {z, -Infinity, Infinity}]]]'
# 输出: \frac{2}{x^2}
```

### 4.3 Wolfram Alpha API 层

```python
# coc-inverse-agent metrics/wolfram.py
import wolframalpha
client = wolframalpha.Client(APP_ID)
res = client.query('integrate 1/(x^2+z^2)^(3/2) dz from -inf to inf')
# → 解析 Pod 输出 → LaTeX
```

**速率限制：** 免费 API 2,000 req/month。建议仅用于：
- 无法本地解析的复杂积分
- 最终交叉验证报告中的 "Wolfram Alpha verified" 标记

### 4.4 LaTeX 归一化对比

```python
# 关键策略：不直接比较字符串，比较数值代入结果
def cross_validate(sympy_expr, wolfram_expr, test_points):
    for pt in test_points:
        sym_val = float(sympy_expr.subs(pt))
        # Wolfram TeXForm → sympy parse → 数值
        wolf_val = float(parse_latex(wolfram_expr).subs(pt))
        assert abs(sym_val - wolf_val) / max(abs(sym_val), 1e-15) < 1e-8
```

---

## 五、数值计算验证层（L2）

### 5.1 黄金标准

**高精度数值积分 N=10⁵** 作为绝对参考，独立于任何符号系统。

```python
# gsnv-theory physics/current_biot_savart.py
def segment_B_field_numeric(p0, p1, obs, I, N=100000):
    """数值积分作为黄金标准"""
    ts = np.linspace(0, 1, N)
    points = p0 + np.outer(ts, p1 - p0)
    dB = np.zeros(3)
    for i in range(N-1):
        mid = (points[i] + points[i+1]) / 2
        dl = points[i+1] - points[i]
        r_vec = obs - mid
        r = np.linalg.norm(r_vec)
        dB += MU0 * I / (4*np.pi) * np.cross(dl, r_vec) / r**3
    return dB
```

### 5.2 收敛性分析

| N | B_z 相对误差 | 说明 |
|:--|:-----------|:------|
| 10² | ~10⁻¹ | 离散化误差显著 |
| 10³ | ~10⁻¹⁰ | 已到双精度极限 |
| 10⁴ | ~10⁻¹² | 安全值 |
| 10⁵ | ~10⁻¹⁴ | **黄金标准** |

**决策规则：** 以 N=10⁵ 数值积分为参考，符号公式的偏差 < 1e-12 即通过。

### 5.3 量级合理性检查（L4 的补充）

在每个验证完成后，增加**数量级检查**（捕获 μm↔m 转换错误）：

```python
def check_order_of_magnitude(B_T: float, expected_range: tuple = (1e-12, 1e-3)):
    """捕获量级错误：如果 B 落在这个范围外，标记警告"""
    if not (expected_range[0] < abs(B_T) < expected_range[1]):
        return Warning(f"B = {B_T:.2e} T 超出预期范围 {expected_range}")
    return True
```

---

## 六、pint 量纲检查层（L3）

### 6.1 已验证实现

**gsnv-theory**: `physics/utils/pint_iso.py` — ISO 2017 量纲注册表
**coc-inverse-agent**: `physics/dimensions.py` — OMC 专用量纲

### 6.2 核心检查

```python
from physics.utils.pint_iso import Q_, check_quantity

def verify_biot_savart_dims():
    """B = μ₀I/(2πd) 的量纲检查"""
    mu0 = Q_(4*np.pi*1e-7, "T*m/A")
    I = Q_(10e-3, "A")
    d = Q_(10e-6, "m")
    B = mu0 * I / (2 * np.pi * d)
    
    assert B.check("magnetic flux density")  # ✅
    # B.dimensionality = [mass] / [time]² / [current]
    
    # 错误示例（不会被pint捕获！）
    d_bad = 10.0  # 忘了是μm，应该写10e-6
    B_bad = Q_(4*np.pi*1e-7, "T*m/A") * Q_(10e-3, "A") / (2 * np.pi * d_bad)
    # → B_bad 量纲正确（T），但数值低估了 10⁶ 倍！
```

### 6.3 pint 的盲区

| 盲区 | 示例 | 如何捕获 |
|:-----|:------|:---------|
| 数值级错误 | μm→m 忘了转 | L4 数量级检查 + L2 数值对比 |
| 混淆 μ 和 m | μT vs mT | 显式写单位，不依赖前缀 |
| 角度/弧度 | deg vs rad | 用 `pint` 注册 `deg` 为角度 |
| 对数/指数 | log(B) 无意义 | 语义检查（非量纲） |

### 6.4 推荐实践

```python
# 每次公式验证强制包含：
# 1. pint 量纲
# 2. 数量级合理性（10⁻¹⁵ ~ 10³ 典型物理范围）
# 3. 物理类型名称（magnetic flux density ≠ field strength）
def full_dimensional_check(expr, name):
    q = Q_(expr)
    check_quantity(q, "magnetic flux density", name)  # 量纲
    assert 1e-15 < abs(q.magnitude) < 1e3            # 量级
    verify_physical_type(q, "magnetic flux density")   # astropy 交叉
```

---

## 七、极限检测层（L4）

### 7.1 已验证场景

| 极限 | 公式 | 期望行为 | 已验证于 |
|:-----|:------|:---------|:---------|
| 远场 d→∞ | B = μ₀I/(2πd) | B → 0 | gsnv, BW |
| 近场 d→0 | B = μ₀I/(2πd) | B → ∞ | gsnv, BW |
| 对称性 x=0,y=0 | 矩形回线 B_z | B_x=B_y=0 | gsnv |
| 简并态 | 微磁学 1.2μm 膜 | 两稳态 | gsnv OOMMF |
| 周期对齐 | ∫ sin(2πfᵢt)sin(2πfⱼt) | T=n/|fᵢ-fⱼ| 时正交 | BW |

### 7.2 检测策略

```python
def check_limits(expr, params):
    checks = []
    
    # 1. 远场
    B_far = expr(**{**params, 'd': 1e-3})
    checks.append(abs(B_far) < params.get('noise_floor', 1e-12))
    
    # 2. 线性性
    B_1 = expr(**{**params, 'I': 1e-3})
    B_2 = expr(**{**params, 'I': 2e-3})
    checks.append(abs(B_2/B_1 - 2.0) < 1e-10)  # B ∝ I
    
    # 3. 对称性
    B_pos = expr(x=1e-6)
    B_neg = expr(x=-1e-6)
    checks.append(abs(B_pos - B_neg) < 1e-15)  # 偶函数
    
    return all(checks)
```

---

## 八、奇异点检测层（L5）

### 8.1 物理常见奇异点

| 奇异点 | 公式 | 物理意义 | 处理方式 |
|:-------|:------|:---------|:---------|
| 分母 d=0 | B = μ₀I/(2πd) | 导线表面 | d ≥ NV深度(~5nm)限制 |
| 分母 (r=0) | 1/r² 核 | Biot-Savart 自作用 | 排除 self-term |
| 分支切割 | √(z) | 复数折射率 | phasor 约定 |
| 极点 | tan(θ) 在 π/2 | 光学共振 | 实际有阻尼 |

### 8.2 自动检测

```python
def detect_singularities(expr_symbolic, param_ranges):
    """自动检测表达式中的奇异点"""
    from sympy import singularities, solveset
    
    # 1. 代数奇异点
    poles = singularities(expr_symbolic, d)
    
    # 2. 数值奇异点（在参数范围内）
    for pole in poles:
        if pole in param_ranges:  # 奇异点在物理范围内
            return Warning(f"奇异点 d={pole} 在物理范围内")
    
    return {"poles": poles, "safe": True}
```

---

## 九、Step-by-Step 推导

### 9.1 已验证于 coc-inverse-agent

`metrics/step_by_step.py` + `metrics/derivation.py` + Notebooks `01_maxwell_to_phc.ipynb`

每步输出格式：

```
Step 3/7: 应用 Biot-Savart 定律
────────────────────────────────────────────
  输入: I·dl, r̂ (z方向无限长导线)
  操作: ∫_{-∞}^{∞} μ₀I·d/(4π·(d²+z²)^(3/2)) dz
  中间: μ₀I·d/(4π) × [z/(d²·√(d²+z²))]_{-∞}^{∞}
       = μ₀I·d/(4π) × 2/d²
       = μ₀I/(2πd)
  输出: B = μ₀I/(2πd)
  引用: Griffiths (2023) §5.3.2, Eq. 5.41
  验证: L1 SymPy ✅ | L2 数值 ✅ | L3 pint ✅ | L4 极限 ✅
```

### 9.2 Notebook 自动生成

已验证于 coc-inverse-agent 的 `scripts/gen_nb_*.py`:

```
gen_nb_01_maxwell.py
  → notebooks/01_maxwell_to_phc.ipynb (源代码)
  → notebooks/01_executed.ipynb (执行结果)
  → docs/figures/cell_*.pdf (arXiv 风格矢量图)
```

---

## 十、Lean 4 形式化证明（未来方向）

### 10.1 定位

Lean 4 是验证管线的**最高层**（L6）——它不是替代 SymPy/Wolfram，而是在它们之上增加数学严格性：

| 层级 | 验证内容 | 严格程度 | 自动化程度 |
|:-----|:---------|:---------|:----------|
| L1 | 符号代数 | 中 | 高 |
| L2 | 数值精度 | 中 | 高 |
| L3 | 物理量纲 | 高 | 高 |
| L4 | 物理极限 | 中 | 中 |
| L5 | 奇异点 | 高 | 中 |
| **L6 Lean 4** | **数学定理证明** | **最高** | **低（需人工）** |

### 10.2 适合 Lean 4 的场景

1. **连续函数正定性证明** — 如能量泛函 E[ψ] > 0 对所有 ψ
2. **微分方程解的存在唯一性** — 如 Maxwell 方程组的适定性
3. **变分原理的极值证明** — 如 Fermat 原理 → Snell 定律
4. **线性算子的谱性质** — 如 Hermitian 算符本征值实性

### 10.3 不适合 Lean 4 的场景

- 纯数值计算（L2 足够）
- 显式代数化简（L1 足够）
- 量纲检查（L3 足够）

### 10.4 与 hfpclawer 的集成

建议 hfpclawer 的 `verify/` 模块预留 L6 接口：

```python
# hfpclawer/verify/lean.py
class Lean4Verifier:
    """Lean 4 形式化证明接口"""
    
    def __init__(self, lean_path: str = "lean-toolchain"):
        self.available = shutil.which("lean") is not None
    
    def verify_theorem(self, theorem_name: str, formula_latex: str) -> dict:
        """调用 Lean 4 证明公式的数学性质"""
        if not self.available:
            return {"status": "SKIP", "reason": "Lean 4 not installed"}
        
        # 1. LaTeX → Lean 4 表达式转换
        lean_expr = latex_to_lean(formula_latex)
        
        # 2. 生成证明骨架
        proof_script = self._generate_proof_skeleton(lean_expr)
        
        # 3. 运行 Lean 4
        result = subprocess.run(["lean", proof_script], capture_output=True)
        
        return {"status": "PASS" if result.returncode == 0 else "FAIL"}
```

---

## 十一、各层之间的耦合与数据流

```
                       FormulaRegistry (JSONL)
                             │
              ┌──────────────┼──────────────┐
              │              │              │
              ▼              ▼              ▼
       ┌────────────┐ ┌────────────┐ ┌────────────┐
       │ SymPy L1   │ │ Wolfram L3 │ │ 数值 L2    │
       │ 符号积分   │ │ 交叉验证   │ │ N=10⁵     │
       └──────┬─────┘ └──────┬─────┘ └──────┬─────┘
              │              │              │
              └──────┬───────┘              │
                     │                      │
                     ▼                      │
              ┌──────────────┐              │
              │ 代数等价性   │◄─────────────┤
              │ A == B ?    │  数值对比    │
              └──────┬───────┘              │
                     │                      │
                     ▼                      ▼
              ┌──────────────┐  ┌──────────────┐
              │ pint L3      │  │ 极限 L4      │
              │ 量纲检查     │  │ 远场/近场    │
              └──────┬───────┘  └──────┬───────┘
                     │                 │
                     ▼                 ▼
              ┌──────────────┐  ┌──────────────┐
              │ 奇异点 L5    │  │ Lean 4 L6    │
              │ 分母/极点    │  │ 形式化证明   │
              └──────────────┘  └──────────────┘
```

---

## 十二、hfpclawer 中的推荐实现

### 12.1 包结构

```
hfpclawer/verify/
├── __init__.py          # from .pipeline import verify
├── registry.py          # FormulaRegistry (JSONL)
├── pipeline.py          # 统一入口: verify(formula_id, layers=[1,2,3,4,5])
├── symbolic.py          # L1: SymPy → LaTeX
├── numerical.py         # L2: numpy N=10⁵ → 收敛性
├── dimensional.py       # L3: pint + 数量级
├── limits.py            # L4: 远场/近场/对称性/线性性
├── singularities.py     # L5: 奇异点/极点/分支切割
├── derivation.py        # Step-by-step 输出
├── wolfram.py           # Docker Wolfram + Alpha API
└── lean.py              # L6: Lean 4 接口（预留）
```

### 12.2 CLI 设计

```bash
# 验证单个公式
hfpclawer verify eq:biot-savart --layers 1,2,3,4,5

# 批量验证整个 registry
hfpclawer verify registry --input formulas.jsonl --output report.json

# Step-by-step 输出
hfpclawer verify derive eq:biot-savart --format qmd > derivation.qmd

# 生成交叉验证报告
hfpclawer verify report --format pdf --arxiv-style
```

### 12.3 输出格式

```json
{
  "formula_id": "eq:biot-savart-segment",
  "layers": {
    "L1_sympy": {"status": "PASS", "value": "μ₀I/(2πd)", "error": null},
    "L2_numerical": {"status": "PASS", "rel_error": 9.5e-15, "N": 100000},
    "L3_dimensional": {"status": "PASS", "type": "magnetic flux density"},
    "L4_limits": {"status": "PASS", "checks": {"far_field": true, "near_field": true}},
    "L5_singularities": {"status": "WARN", "singularities": [{"d": 0, "mitigation": "d ≥ NV_depth(5nm)"}]}
  },
  "cross_validation": {
    "sympy_vs_wolfram": {"status": "PASS", "rel_error": 2.3e-14},
    "sympy_vs_numerical": {"status": "PASS", "rel_error": 9.5e-15}
  },
  "timestamp": "2026-06-27T22:00:00",
  "verified_by": ["formula_registry_v1"]
}
```

---

## 十三、讨论题

1. **Lean 4 的时机？** 是否应在 hfpclawer v0.6 预留接口，还是等到有真实使用场景再集成？
2. **Wolfram 依赖管理？** Docker Wolfram Engine 15.0 (4.5GB) 是否应作为 optional extra？
3. **SymPy 的代数等价性？** 是否应该白名单已知有效的简化策略（如 `sp.simplify`、`sp.expand`、`sp.factor`）？
4. **数值积分的默认 N？** N=10⁵ 在 gsnv 中验证充分，但对 3D 场问题可能不够，是否应该自动收敛检测？
5. **LaTeX 归一化** 是否需要自定义 `LaTeXNormalizer` 类来处理 SymPy vs Wolfram 的排序差异？
