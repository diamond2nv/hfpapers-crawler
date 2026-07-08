# hfpclawer 三项改进设计

> **状态**: 分析/设计阶段，待确认后实施
> **日期**: 2026-07-12

---

## 1. PyPI 自动发布 CI（待讨论 / 暂停）

### 现状

| 条目 | 状态 |
|:-----|:------|
| 最新 PyPI 发布 | v0.4.x（2026-05 之前） |
| 当前版本 | v0.8.1 — **未发布到 PyPI** |
| 发布方式 | 手动 `twine upload` |
| CI | 无 |

### 阻塞因素

1. **`arxiv extra` git dep** — `pyproject.toml` 中有:
   ```toml
   arxiv = ["arxiv-metadata-service @ git+https://github.com/...@v0.2.0"]
   ```
   PyPI 不允许 git 依赖。解决方案：`extras_require` 用版本范围而非 git tag，或分两步发布（先发不含 extras 的 core 包）。

2. **版本双源** — `pyproject.toml` 和 `hfpapers/__init__.py` 各存一份版本号。解法：统一到 `importlib.metadata`（已有 v0.5.x 的准备但没启用）。

3. **测试依赖 numpy/scipy** — `pyproject.toml` 未分组为 `test` extra。

### 建议方案（待确认）

```yaml
发布策略:
  核心包 (hfpclawer-core):
    - 不含 git dep 的 extras
    - pip install hfpclawer 直接可用（arXiv 搜索功能降级为纯 arXiv API）
  
  完整包 (hfpclawer[arxiv]):
    - 含 extras（需先手动 `pip install arxiv-metadata-service`）
    - 文档说明可选依赖
  
  CI Workflow (GitHub Actions):
    - tag push → build → twine check → twine upload PyPI
    - 自动从 __init__.py 读取版本
```

**决策点**：是否拆分为 `hfpclawer-core` + `hfpclawer[arxiv]`？还是等 arxiv-metadata-service 也发布到 PyPI？

---

## 2. audit-verify 注册为 `hfpclawer audit cron-verify` 子命令 ✅ 可实施

### 设计

整合现有 `scripts/hfpclawer-audit-verify.py` 为 `hfpclawer audit` 的一个子 action：

```
hfpclawer audit cron-verify                     # 审核所有未验证的 cron 论文
hfpclawer audit cron-verify --since 2026-06-01   # 只审最近入库的
hfpclawer audit cron-verify --retraction-check   # 只做撤稿检测
hfpclawer audit cron-verify --all               # 强制全文再验证
hfpclawer audit cron-verify --dry-run            # 预览模式，不实际写入
```

### 代码变化

| 文件 | 变更 |
|:-----|:------|
| `hfpapers/cli.py` | 在 `audit()` 函数的 `elif action ==` 链中追加 `elif action == "cron-verify":` |
| `hfpclawer/audit/cron_verify.py` | **新建** — 从 `scripts/hfpclawer-audit-verify.py` 提炼的核心逻辑，暴露 `batch_cron_verify()` 函数 |
| `scripts/hfpclawer-audit-verify.py` | 降级为 CLI 封装，调用 `hfpclawer.audit.cron_verify.batch_cron_verify()` |
| `ACTION_DESCRIPTIONS` | 追加 `cron-verify` 条目 |

### 与现有 `audit verify` 的区别

| | 现有 `audit verify` | 新增 `audit cron-verify` |
|:--|:-------------------|:------------------------|
| 目标 | 人工输入 citation 文本做学术不端检测 | 对 paper_store 中未验证的 cron 论文做批量 Crossref 验证 |
| 输入 | 字符串（论文标题） | paper_store DB 记录 |
| 输出 | 单条结果报告 | 批量统计 + 更新 DB |
| 速度 | 1 条 / 2s | N 条 / 1.1s 每条 |

---

## 3. 第三方 0-token cron 模板 ✅ 可实施

### 设计目标

第三方用户从零开始，只需：
```
pip install hfpclawer
hfpclawer cron init --domain "coc,gsnv,fusion" --output ~/papers
# 生成 crontab + Hermes skill + 验证脚本
```

### 三件交付物

#### 3.1 模板脚本 `scripts/hfpclawer-cron-fetch.sh`

```bash
#!/bin/bash
# hfpclawer-cron-fetch.sh — 0-token arXiv 定时采集模板
#
# 第三方用户部署：
#   1. 复制此脚本，修改 DOMAINS 和 DAYS
#   2. crontab -e 添加：
#      0 9 * * 1 /path/to/hfpclawer-cron-fetch.sh
#
# 设计原则：
#   - 0 LLM token（纯 bash + python3 CLI，无需 Hermes）
#   - idempotent：重复跑安全，只入库新论文
#   - silent when empty：无新论文输出空 → 不触发通知
#   - 可独立运行，也可被 Hermes cronjob 的 no_agent=true 调用

set -euo pipefail

# ═══════════ 用户配置区 ═══════════
# 修改以下变量适配你的领域
DOMAINS="coc,gsnv,fusion,neural-pde"
DAYS=7
OUTPUT_DIR="${HOME}/hfpclawer-data"
HFPCLAWER_BIN="hfpclawer"  # 或在 venv 中指定完整路径
# ══════════════════════════════════

mkdir -p "${OUTPUT_DIR}"
cd "${OUTPUT_DIR}"

NEW_FILE="${OUTPUT_DIR}/arxiv-new.jsonl"
ALL_FILE="${OUTPUT_DIR}/arxiv-all.jsonl"

# Phase 1: arXiv 搜索（调用 hfpclawer 核心搜索器）
IFS=',' read -ra DOMAIN_LIST <<< "${DOMAINS}"
NEW_COUNT=0
for DOMAIN in "${DOMAIN_LIST[@]}"; do
    ${HFPCLAWER_BIN} search --domain "${DOMAIN}" --days "${DAYS}" \
        --output "${NEW_FILE}" --append 2>/dev/null || true
done

# Phase 2: 去重合并到 all.jsonl
if [ -f "${NEW_FILE}" ]; then
    python3 -c "
import json, os
new_path = '${NEW_FILE}'
all_path = '${ALL_FILE}'
seen = set()
if os.path.exists(all_path):
    with open(all_path) as f:
        for line in f:
            p = json.loads(line)
            if p.get('arxiv_id'):
                seen.add(p['arxiv_id'])
new_papers = []
with open(new_path) as f:
    for line in f:
        p = json.loads(line)
        aid = p.get('arxiv_id','')
        if aid and aid not in seen:
            new_papers.append(p)
            seen.add(aid)
if new_papers:
    with open(all_path, 'a') as f:
        for p in new_papers:
            f.write(json.dumps(p, ensure_ascii=False) + '\n')
    print(f'{len(new_papers)}')
    # 记录到 paper_store
    ${HFPCLAWER_BIN} store import --file \"${NEW_FILE}\" --skip-crossref 2>/dev/null
fi
"
fi

# 清理临时文件
rm -f "${NEW_FILE}"
```

#### 3.2 Hermes Skill `hfpclawer-cron-fetch`

```yaml
# ~/.hermes/skills/hfpclawer-cron-fetch/SKILL.md
---
name: hfpclawer-cron-fetch
description: 基于 hfpclawer 的 0-token arXiv 定时采集技能
---

# hfpclawer-cron-fetch

## 用途
第三方用户部署自己的 arXiv 论文采集流水线，0 token，纯 shell + hfpclawer CLI。

## 快速开始
```bash
# 1. 安装 hfpclawer
pip install hfpclawer

# 2. 初始化
hfpclawer cron init --domain "coc,gsnv" --output ~/papers

# 3. 验证
hfpclawer cron check
```

## 配合 Hermes cronjob
```yaml
# Hermes config.yaml 中注册
cron:
  - name: my-arxiv-fetch
    schedule: "0 9 * * 1"
    script: ~/.hermes/scripts/hfpclawer-cron-fetch.sh
    no_agent: true          # 0 token！
    deliver: origin
```

## 环境变量
| 变量 | 默认值 | 说明 |
|:-----|:-------|:------|
| HFPCLAWER_DOMAINS | "coc,gsnv,fusion,neural-pde" | 逗号分隔的领域 |
| HFPCLAWER_DAYS | 7 | 回溯天数 |
| HFPCLAWER_OUTPUT | ~/hfpclawer-data | 数据目录 |
```

#### 3.3 `hfpclawer cron` CLI 子命令

```
hfpclawer cron init        # 交互式初始化：指定领域 → 生成模板脚本 + crontab
hfpclawer cron check        # 检查上次运行状态 + paper_store 统计
hfpclawer cron run          # 手动触发一次采集
hfpclawer cron import       # 将本地 JSONL 导入 paper_store（skip_crossref）
```

### 第三方用户体验时间线

```
Time 0:  pip install hfpclawer
         hfpclawer cron init --domain "coc,fusion"
         # 输出: ✓ 已创建 ~/hfpclawer-data/ + crontab 条目
         #       ✓ 可运行 hfpclawer cron run 手动测试

Time +1min:  hfpclawer cron run --dry-run
             # 输出: 发现 3 篇新论文（未实际写入）
             # 确认后: hfpclawer cron run

Time +1week: （cron 自动触发，无输出 = 无新论文）
             hfpclawer cron check
             # 输出: paper_store 共 47 篇
             #       上次运行: 2026-07-19 09:00 (3 篇新增)
```

---

## 实施顺序

| 步骤 | 内容 | 预估 |
|:-----|:------|:----|
| 1 | `hfpclawer/audit/cron_verify.py` — 从脚本提炼核心逻辑 | 1h |
| 2 | `cli.py` 追加 `cron-verify` action | 0.5h |
| 3 | `scripts/hfpclawer-cron-fetch.sh` — 第三方模板 | 1h |
| 4 | `hfpclawer cron` CLI 子命令组 | 2h |
| 5 | Hermes skill `hfpclawer-cron-fetch` | 0.5h |
| 6 | PyPI CI（暂停，先讨论） | — |

---

**待你确认后开始实施**。尤其第 1 项的 PyPI 发布策略（拆分 vs 等待依赖包上 PyPI）需要你的方向。
