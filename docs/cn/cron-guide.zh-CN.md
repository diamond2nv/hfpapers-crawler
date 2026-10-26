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

## 轮次运行器：`scripts/cron_round.py`（v0.19.14）

现在入库一轮是一条命令：查轴、与库比对、只入库新的，并证明去重链路仍然有效。
它取代了每轮一次性的脚本；那些脚本留在 `scripts/` 作为来源记录，
并已标注被取代。

```bash
python3 scripts/cron_round.py \
    --source cron-YYYY-MM-DD-roundN \
    --axis 'all:"AI for science" AND all:agent' \
    --pick 2610.06986 \
    --dedup-regression 2610.06986v1 \
    --audit-forms --json-out /tmp/round.json
```

退出码：`0` 正常，`1` 断言被违反，`2` 用法或环境错误。查重探针若对已入库 id 返回
`is_new=True`，会**故意让整轮失败**——这正是那些一次性脚本反复隔了好几轮
才靠人发现的那项检查。

### 长时使用教给我们的

1. **身份是裸 id。** `2610.06986` 与 `2610.06986v1` 是同一篇；按原字符串比较会把
   两条都放进库。先归一：`normalize_arxiv_id()` 是解析，而 `split("v")` 这种
   捷径不是——它在任意 `v` 上切。
2. **绝不要写第二个 arXiv 客户端。** 有一轮用了 `CERT_NONE`，白白关掉 TLS 校验。
   `arxiv_lookup._http_get` 早已处理 `406` 边缘指纹，且保持 TLS 开启。
3. **把整个 `search_query` 做 `urlencode` 会把它变成空查询。** `A+AND+B` 里的 `+`
   变成 `%2B`，API 于是读到另一个查询。`build_axis_url()` 让运算符字面保留。
4. **`year=0` 是结构性的，不是某一行坏了。** `ensure_paper` 不接收 `year`；
   运行器从 `published` 回填。年份大多为 0 时，任何按年的问题都答不了。
5. **`--audit-forms` 是漂移警报。** 它找出同一篇被多种 id 形态记录的情况——
   `2609.09203` 那条标题为 `x` 的重复，本可以在变成永久记录之前就现形。
6. **把轮次脚本提交进仓。** 一次性脚本留在未跟踪状态会断掉证据链：复盘文案
   引用了它，而别的机器取不到"当时是用什么代码筛出这些论文"。

### 在信任一轮之前

```bash
python3 scripts/cron_round.py --source smoke --pick <已入库-id> --dedup-regression <已入库-id> --dry-run
python3 scripts/cron_round.py --source smoke --audit-forms --dry-run | python3 -m json.tool
hfpclawer store stats          # 你声称的增量必须对得上
```

一轮可信，当且仅当：库增量等于 `is_new=True` 的条数、对已入库 id 的回归探针
返回 `False`、且 `--audit-forms` 没有新增重复形态对。
