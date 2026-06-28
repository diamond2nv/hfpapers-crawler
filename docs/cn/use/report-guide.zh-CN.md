# 报告指南 — `hfpclawer verify report`

从公式注册表生成发表级的验证报告。

## 用法

```bash
# LaTeX 片段（独立可编译 .tex 文档）
hfpclawer verify report <fid>

# Quarto .qmd 文档（一键 PDF 输出）
hfpclawer verify report <fid> --qmd > report.qmd

# 自定义标题
hfpclawer verify report <fid> --qmd --title "附录：公式验证" > appendix.qmd
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

### 2. Quarto .qmd（`--qmd`）

生成完整 Quarto `.qmd` 文档，包含：

- YAML 前置元数据（ctexart + Liberation Serif + booktabs）
- 验证正文包裹在 `{=latex}` 原始块中
- 可直接 `quarto render --to pdf`

```bash
hfpclawer verify report eq:biot-savart --qmd > appendix.qmd
quarto render appendix.qmd --to pdf
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

# 4. 生成 Quarto .qmd（独立 PDF）
hfpclawer verify report eq:maxwell-faraday --qmd > appendix.qmd
quarto render appendix.qmd --to pdf
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
