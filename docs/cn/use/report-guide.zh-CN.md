# 报告指南 — `hfpclawer verify report`

从公式注册表生成发表级的验证报告。

## 用法

```bash
# LaTeX 片段（独立可编译 .tex 文档）
hfpclawer verify report <fid>

# Quarto .tex 文档（一键 PDF 输出）
hfpclawer verify report <fid> --qmd > report.tex
quarto render report.tex --to pdf

# 自定义标题
hfpclawer verify report <fid> --qmd --title "附录：公式验证" > report.tex
```

## 输出模式

### 1. LaTeX 片段（默认）

输出独立 `.tex` 文档到 stdout，包含：

- **基本信息表**：FID、LaTeX 公式、物理维数、来源、标签、可信度等级
- **验证流水线**：L1→L5 逐层结果与通过/失败标记
- **CAS 等价性证明**：SymPy ↔ Wolfram Engine 代数对比（`align*` 环境）
- **数值验证表**：计算值与期望值对比
- **发表建议**：A/B/C 三级可信度

输出是自包含 `.tex` 文件，使用 `documentclass{article}` + `ctex` 支持中文。编译方法：

```bash
hfpclawer verify report eq:biot-savart > appendix.tex
xelatex appendix.tex
```

或嵌入已有论文：

```latex
\input{appendix_verify.tex}
```

### 2. Standalone .tex（`--qmd`）

使用 `ctexart` 生成包含标题页的标准 LaTeX 文档，可直接编译或通过 Quarto 渲染：

```bash
hfpclawer verify report eq:biot-savart --qmd > report.tex
xelatex report.tex              # 直接编译
quarto render report.tex --to pdf  # 通过 Quarto
```

## PDF 渲染前置条件

### Quarto 安装（国内网络友好）

```bash
VERSION="1.10.2"
aria2c -x 5 -s 5 "https://ghproxy.net/https://github.com/quarto-dev/quarto-cli/releases/download/v${VERSION}/quarto-${VERSION}-linux-amd64.tar.gz"
tar -xzf quarto-${VERSION}-linux-amd64.tar.gz -C /tmp/
mkdir -p ~/.local/share/quarto
mv /tmp/quarto-${VERSION} ~/.local/share/quarto/${VERSION}
ln -sf ~/.local/share/quarto/${VERSION}/bin/quarto ~/.local/bin/quarto
```

### TinyTeX 安装

```bash
quarto install tinytex
export PATH="$HOME/.TinyTeX/bin/x86_64-linux:$PATH"
```

持久化到 shell 配置：

```bash
echo 'export PATH="$HOME/.TinyTeX/bin/x86_64-linux:$PATH"' >> ~/.bashrc
```

### 首次编译

首次 `quarto render` 需要 2-3 分钟下载 LaTeX 宏包。后续编译约 15 秒。

```bash
quarto render report.qmd --to pdf
ls -lh report.pdf
```

## 完整工作流

```bash
# 1. 添加公式
hfpclawer verify add eq:maxwell-faraday "$\nabla \times \mathbf{E} = -\frac{\partial \mathbf{B}}{\partial t}$" \
  --dim "V/m²" --tag electromagnetism --tag maxwell

# 2. 运行验证
hfpclawer verify fid eq:maxwell-faraday

# 3. 生成 LaTeX 报告（嵌入论文）
hfpclawer verify report eq:maxwell-faraday > appendix_faraday.tex

# 4. 生成 Standalone .tex（Quarto PDF）
hfpclawer verify report eq:maxwell-faraday --qmd > appendix.tex
quarto render appendix.tex --to pdf
```

## 可信度等级

| 等级 | 条件 | 含义 |
|------|------|------|
| **A** | 全部通过（6/6） | 可发表 — 双 CAS 独立验证 + 数值 + 量纲 + 极限 |
| **B** | ≥5/6 通过 | 审查未通过层后再发表 |
| **C** | <5/6 通过 | 重新验证并修复后再发表 |

## 已知问题

1. **`\section` 与 `ctexart`**：LaTeX 片段使用 `\section`，需要 `ctexart` 或 `article` 文档类。默认前置声明已包含 `ctex`。
2. **Wolfram Engine**：CAS 交叉验证需要正在运行的 Wolfram Engine Docker 容器。无容器时 L1b 跳过并标注。
3. **数值检查**：L2 数值验证需要公式条目包含 `numeric_check` 字段 — 大部分公式会优雅跳过 L2。
4. **长 LaTeX**：超过 ~80 字符的公式可能在表格中被截断。基本信息行仍保留完整 LaTeX。

---

## 附录：验证流水线层参考

*适用于 hfpclawer ≥ v0.7.3。未来层以 † 标记。*

验证报告对公式进行 6 层逐级检验。每层针对一种特定的失效模式，使用独立的工具链：

| 层 | 名称 | 检查内容 | 工具 | 典型通过/失败 |
|----|------|---------|------|--------------|
| **L1** | 符号推导 | LaTeX → SymPy 解析 → 化简。捕获语法错误、未定义符号、发散积分。 | SymPy | `\sin^2 x + \cos^2 x` → `1` ✅；格式错误的 LaTeX → 解析失败 ❌ |
| **L1b** | CAS 交叉验证 | 同一 LaTeX 分别在 SymPy 和 Wolfram Engine 中求值；通过 9 种策略（simplify/expand/together/trigsimp/powsimp/factor/derivative/ratio/numeric_fallback）证明代数等价性。 | SymPy + Wolfram Engine (Docker) | `(x-1)(x+1)` vs `x^2-1` → expand ✅；`\sin^2 x` vs `1-\cos^2 x` → trigsimp ✅ |
| **L2** | 数值验证 | 代入具体数值，计算结果与期望值在 5% 容差内比较。 | NumPy + SymPy | `q=1.6e-19, E=1, B=0, v=0` → `F=1.6e-19` ✅；μm→m 相差 10⁶× ❌ |
| **L3** | 量纲分析 | 通过 pint 验证公式的物理维数是否与声明的量一致（如力 → `[M·L·T⁻²]`）。 | pint | `F=ma` → `[M·L·T⁻²]` ✅；`F=mv` → 维数错误 ❌ |
| **L4** | 物理极限 | 符号极限测试：远场 (var→∞) 应趋于 0 或常数；近场发散检测。 | SymPy limit() | `1/r` 在 r→∞ → 0 ✅；`1/r` 在 r=0 → 发散 ⚠️ |
| **L5** | 奇异点检测 | AST 遍历器查找分母为零、对数分支点、反幂奇异点。 | SymPy preorder_traversal | `\frac{1}{r}` → 标记 `1/r` ⚠️；`\log(z-1)` → 标记 `log(z-1)` ⚠️ |

### 如何解读未通过层

某一层未通过**不代表公式有错**，只表示检查器发现了不能自动排除的信号：

| 报告状态 | 可能含义 |
|---------|---------|
| ❌ L5（奇异点） | `1/r` 在原点—物理上有效但被标记；需人工复核并添加说明 |
| ❌ L1（解析） | LaTeX 拼写错误或不支持的宏（如 `\bm` 应为 `\mathbf`） |
| ❌ L1b（CAS） | SymPy 与 Wolfram 结果不一致—可能是真正的差异或化简路径分歧 |
| ❌ L3（量纲） | 单位不匹配—如力公式输出了 `[M·L·T⁻¹]` 而非 `[M·L·T⁻²]` |

### 未来层（†）

| 层 | 名称 | 规划能力 | 目标版本 |
|----|------|---------|---------|
| **L6** † | 形式化证明 | Lean 4 定理证明器集成。将已验证的 SymPy 表达式翻译为 Lean `calc` 块，通过 `simp` / `ring` / `field_simp` 自动消解。 | v0.8+ |
| **L7** † | 质量指标 | 对给定测试用例，与发表值进行基准数值精度对比。 | v0.9+ |
| **L8** † | 文献一致性 | 与 arXiv/DOI 的已知结果交叉验证—检查公式的数值预测是否匹配已建立的实验/计算基线。 | v1.0+ |
