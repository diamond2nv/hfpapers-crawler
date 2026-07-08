# hfpclawer Cron 自动化 — 用户指南

## 快速上手（3分钟）

### 1. 安装

```bash
pip install hfpclawer
```

### 2. 初始化

```bash
# 选一种：
hfpclawer cron init --name 我的领域 --query "cat:cs.AI+AND+abs:neural+operator"
hfpclawer cron init --name 我的领域 --keywords "神经算子, 深度学习, PDE"
hfpclawer cron init --name 我的领域 --from-config /path/to/existing/config.yaml
```

创建：
- `~/.hfpclawer/config.yaml` — 编辑你的 arXiv 查询
- `~/.hfpclawer/scripts/hfpclawer-cron-fetch.sh` — 用于系统 crontab
- `~/.hfpclawer/data/paper_store.db` — 论文数据库

### 3. 自定义

```bash
$EDITOR ~/.hfpclawer/config.yaml
```

添加多个领域：

```yaml
cron:
  domains:
    - name: "机器学习"
      query: "cat:cs.LG+AND+abs:attention"
      category: "ML"
    - name: "物理"
      query: "cat:physics.comp-ph+AND+abs:neural+operator"
      category: "neural-operator"
  post_verify: true
```

### 4. 运行

```bash
hfpclawer cron run
```

### 5. 定时调度

**系统 crontab（0 token）：**
```bash
crontab -e
59 18 * * 1  ~/.hfpclawer/scripts/hfpclawer-cron-fetch.sh --json
```

**Hermes cron（LLM 驱动）：**
```bash
hermes cron create \
  --schedule "0 18 * * 1" \
  --prompt "运行 'hfpclawer cron run' 并总结新论文" \
  --skills hfpclawer-cron
```

## 命令参考

| 命令 | 说明 |
|:-----|:------|
| `hfpclawer cron init` | 初始化 ~/.hfpclawer/ 配置和脚本 |
| `hfpclawer cron check` | 查看配置状态 |
| `hfpclawer cron run` | 执行获取+入库流水线 |
| `hfpclawer cron import` | 从 candidates/jsonl 导入 |
| `hfpclawer audit cron-verify` | 延迟 Crossref 验证+撤稿检测 |

## 数据库位置（三级优先级）

paper_store.db 按以下优先级确定：

1. **`HFPCLAWER_DATA` 环境变量** — CI/docker 场景覆盖
2. **`~/.hfpclawer/data/paper_store.db`** — 默认路径
3. **自定义 `--data-dir`** — 生成脚本中写入绝对路径

## 验证流水线

Cron 导入跳过 Crossref 验证以加速（`skip_crossref=True`）。之后可延期验证：

```bash
# 验证所有未验证的 cron 论文
hfpclawer audit cron-verify

# 只检查撤稿（0 Crossref 调用）
hfpclawer audit cron-verify --retraction-only

# 强制重新验证所有 cron 论文
hfpclawer audit cron-verify --all
```

## 与 hfpclawer paper_store 配合使用

Cron 导入后，论文以 `cron:<领域>` 来源标签出现在 paper_store 中：

```bash
hfpclawer store stats                        # 查看所有论文统计
hfpclawer store search --keyword 神经网络    # 搜索导入的论文
hfpclawer cron check                         # 查看 cron 专有统计
```
