# scripts/ — AGENTS guide（注册表 · 判据 · 依赖 · 生命周期）

这份文件是仓库披露的**第二层**，读法：

```
AGENTS.md（根：全局规则）
  └─ scripts/AGENTS.md（本文件：每个脚本是什么、承诺什么、谁消费、何时可退役）
       └─ 脚本自己的 docstring + `--help`（实现细节）
```

本文件不重复根规则。按需读一节，不要通读：

| 你要做的事 | 读 | 跳过 |
|:--|:--|:--|
| 发布 / 打 tag / 推送 | §2 判据 + §1 注册表（`release`、`recut`、`publish`） | — |
| 改门禁、改脱敏模式、改退出码 | §2 判据 + §4「修改」 | — |
| 新增脚本 | §4「新增」checklist | §3 |
| 判断某文件还有人用吗 | §1 注册表 `状态`/`调用者` 列 | §2 |
| 排查 cron 管线 | §1 的 `cron` 行 + `docs/cron-guide.md` | §2 |

下面的注册表是**机器核对**的（`tests/test_scripts_registry.py`）：每个 tracked 文件必须且只能
出现一次；每行必须有合法类型与状态；`gate` 行必须同时出现在 §2（有退出码契约）；`superseded`
行的文件头必须真的写着 `SUPERSEDED`；每个 `gate` 必须有外部消费者。新增脚本不登记 ⇒ 测试红。
这就是它的用途。

## 1. 注册表

类型词表：`gate`（有判据与退出码契约）· `publish`（在两条血统/两个 host 之间搬内容）·
`cron`（定时取数 wrapper）· `pipeline`（数据搬运）· `one-off`（跑过一次，留成因）·
`template`（示例/配置，无代码）· `lib`（被读取，从不直接执行）。

| 文件 | 类型 | 入口 | 调用者 | 判据 / 产物 | 状态 |
|:--|:--|:--|:--|:--|:--|
| `changelog_guard.py` | gate | `python3 scripts/changelog_guard.py VERSION` | `release.sh`、`recut-public.py`、`tests/test_gates.py` | 该版本在 `docs/CHANGELOG.md` 或 archive 有条目 | active |
| `changelog_rotate.py` | gate | `python3 scripts/changelog_rotate.py [--check\|--verify-history\|--refresh\|--dry-run]` | `release.sh`、`recut-public.py`、`tests/test_gates.py` | 窗口 ≤ 24576 B；头部自述字节数 == 实际；条目不丢失 | active |
| `pre-push` | gate | 安装为 `.git/hooks/pre-push`（源文件即本仓 `scripts/pre-push`） | git（每次 push） | 门1 版本 · 门2 脱敏 · 门3 内网布局 · 门4 公开远端 tag 形状 + 拒推 dev `main` | active |
| `sanitize-patterns.sh` | lib | `source scripts/sanitize-patterns.sh`（被 pre-push / publish-public.sh 读取） | `pre-push`、`publish-public.sh`、`tests/test_sanitization.py` | 脱敏模式**唯一来源**（改一处三处生效） | active |
| `doc_audit.py` | gate | `python3 scripts/doc_audit.py` | 手工 | C1–C7 文档面检查；**advisory，不进发布门** | active |
| `version-check.sh` | gate | `bash scripts/version-check.sh [--fix]` | `release.sh`（bump 前）、手工 `--fix` | `pyproject` 与最新 tag 同号，否则拒绝 bump（防把漂移掩盖成新版本） | active |
| `release.sh` | publish | `bash scripts/release.sh VERSION [--dry-run]` | 手工（维护者） | dev 线 bump + commit + tag；`--push` 已被拒绝 | active |
| `recut-public.py` | publish | `python3 scripts/recut-public.py --mode {release,sync} --version X.Y.Z [--push]` | 手工（维护者） | 公开线快照 + 四道门（§2）；默认 dry-run | active |
| `publish-public.sh` | publish | `bash scripts/publish-public.sh [VERSION --push [--no-tag]\|--check\|--status]` | `recut-public.py`、手工 | GitHub 分支/（release 时）tag 推送 + 读回验证 | active |
| `publish.sh` | publish | `bash scripts/publish.sh [test\|prod]` | 手工（维护者） | PyPI 构建 + twine 上传；自带门禁只有 twine 存在性检查 | active |
| `cron_round.py` | pipeline | `python3 scripts/cron_round.py --source NAME [--pick ID]…` | 手工、`docs/cron-guide.md` | 一轮采集：轴查询 → 归一化 diff → ingest → 回归断言 | active |
| `cron-multi-repo-arxiv-fetch.py` | cron | `python3 scripts/cron-multi-repo-arxiv-fetch.py --days N [--domain D]` | 系统 crontab（经 `cron-*weekly*.sh` 部署副本） | arXiv 多域采集 JSONL（0 token） | active |
| `cron-live-to-hfpclawer.py` | pipeline | `python3 scripts/cron-live-to-hfpclawer.py` | 系统 crontab | cron JSONL → paper_store 桥接（0 token） | active |
| `cron-coc-weekly-fetch.sh` | cron | `bash scripts/cron-coc-weekly-fetch.sh` | 系统 crontab（部署副本在 `~/.hermes/scripts`） | 周采集 wrapper：腔光机械 | template |
| `cron-fusion-daily-fetch.sh` | cron | `bash scripts/cron-fusion-daily-fetch.sh` | 系统 crontab（部署副本） | 日采集 wrapper：核聚变（带重试） | template |
| `cron-gsnv-weekly-fetch.sh` | cron | `bash scripts/cron-gsnv-weekly-fetch.sh` | 系统 crontab（部署副本） | 周采集 wrapper：钢轨 NV | template |
| `cron-neural-pde-weekly-fetch.sh` | cron | `bash scripts/cron-neural-pde-weekly-fetch.sh` | 系统 crontab（部署副本） | 周采集 wrapper：神经算子 PDE | template |
| `hfpclawer-cron-fetch.sh` | cron | `bash scripts/hfpclawer-cron-fetch.sh` | `hfpclawer cron init` 生成；系统 crontab | `no_agent=true` 模式取数（0 token） | template |
| `cron-repos.example.json` | template | 复制 `scripts/cron-repos.example.json` 为 `cron-repos.local.json`（gitignored） | `cron-multi-repo-arxiv-fetch.py`、`HFPCLAWER_REPO_MAP` | 域名 → 仓库路径映射；示例里不得有真实仓库名 | template |
| `researcher-audit/researcher_audit.py` | pipeline | `python3 scripts/researcher-audit/researcher_audit.py` | 手工 | 研究者论文审计；真实 `people.yaml` 已 ignore | active |
| `researcher-audit/README.md` | template | 人工阅读 `scripts/researcher-audit/README.md` | 人工阅读 | 说明哪些文件私有、哪些可公开 | template |
| `researcher-audit/people.example.yaml` | template | 复制 `scripts/researcher-audit/people.example.yaml` 为 `people.yaml`（gitignored） | `researcher_audit.py` | 占位条目模板 | template |
| `hfpclawer-audit-verify.py` | pipeline | `python3 scripts/hfpclawer-audit-verify.py` | `hfpclawer/audit/cron_verify.py` | 异步交叉审核 + 撤稿检测 | active |
| `download_arxiv_oai.py` | pipeline | `python3 scripts/download_arxiv_oai.py` | `hfpclawer/download/oai.py` | OAI-PMH 批量元数据 → SQLite FTS5 | active |
| `ai4math_search.py` | one-off | `python3 scripts/ai4math_search.py` | 无（手工，2026-07-09） | 批量检索写入 paper_store + wiki | active |
| `fusion_enrich_graph.py` | one-off | `python3 scripts/fusion_enrich_graph.py` | 无（手工） | 图谱补中国机构聚变论文/人/边 | active |
| `fix_failed_reason.py` | one-off | `python3 scripts/fix_failed_reason.py` | 无（2026-05-14 一次性修复） | 修 `AsyncPdfDownloader` 空错误串 | one-off |
| `run_batch_full.py` | one-off | `python3 scripts/run_batch_full.py` | 无（2026-05-14） | 全量批处理驱动 | one-off |
| `cron_round_2026_10_09.py` | one-off | `python3 scripts/cron_round_2026_10_09.py` | 无 | 该轮采集的成因记录（结论已进 CHANGELOG） | superseded |
| `cron_round_2026_10_10.py` | one-off | `python3 scripts/cron_round_2026_10_10.py` | 无 | 同上 | superseded |

三类「仓库内没有调用者」不是漏登记：`cron` 模板的运行时副本在 `~/.hermes/scripts`（系统
crontab 调那份，不调仓里的）；`one-off` 是手工跑的；`superseded` 是留档的。

## 2. 判据（gate 才算）

一条判据必须能被别人**重跑**，所以每条都写清命令、退出码、失败含义、谁消费。

| 脚本 | 命令 | 退出码 | 失败意味着 | 谁消费 |
|:--|:--|:--|:--|:--|
| `changelog_guard.py` | `… VERSION` | 0 已记录 · 1 未记录 · 2 用法/读文件错 | 该版本不能被 tag | `release.sh`、`recut`（release 模式） |
| `changelog_rotate.py` | `… --check` | 0 窗口内 · 1 需轮转 | 发布前必须先轮转 | `release.sh`、`recut` |
| `changelog_rotate.py` | `… --verify-history` | 0 无丢失 · 2 守恒失败 | 有条目被吞 | 同上 |
| `changelog_rotate.py` | `… --refresh` | 0 头部已正确或被修正 | 声明字节数与实际不符（数字本身改变长度） | `release.sh`（bump 前）、手工 |
| `pre-push` | 装成 hook；手工可 `printf '<refs 行>' \| sh scripts/pre-push <remote> <url>` | 0 通过 · 1 拒绝 | 拒绝推送并打印原因与修法 | git；公开远端另加门4 |
| `version-check.sh` | `bash … [--fix]` | 0 同号 · 1 不同号 | `pyproject` 与 tag 漂移；`release.sh` 据此**拒绝 bump** | `release.sh`（bump 前）、手工 `--fix` |
| `doc_audit.py` | `python3 …` | 不作为判据 | **advisory**：看 `TOTAL findings` | 手工 |
| `publish-public.sh`（`--check`） | `bash … --check` | 0 干净 · 1 有命中 | 有敏感/内网内容 | 发布前手工、`recut` 复用 |
| `publish-public.sh`（`--status`） | `bash … --status` | 0 | 打印待推提交数 / 公开 tag / 已同步高水位 | 手工 |
| `recut-public.py` | 见注册表 | 0 完成 · 1 门禁失败 · 2 preflight 拒绝 | 1 = 内容不合格；2 = 请求本身不该发 | 手工 |

**发布链的门序**（一次真实 sync 会逐条打印，缺一条就是没跑）：

```
public-only paths → changelog coverage（release 必需 / sync 跳过）→ sanitization → snapshot tests
→ [--push] publish-public.sh 的脱敏门 → git push → pre-push hook（门1–4）→ 读回 ls-remote
```

`release` 与 `sync` 的区别、高水位、tag 形状限制见 `docs/ROADMAP.md` 与 `CHANGELOG.md` v0.20.0 /
v0.20.1 条目。一句话：`release` 产 tag + GitHub Release + PyPI；`sync` 只产一个带 `Public-Sync:`
trailer 的提交，且**同一版本不能二次 sync**（一版一树）。

## 3. 依赖

**外部**：`python3`（≥3.10，同 `requires-python`）、`git`、`sh`/`bash`；发布侧另需 `ssh`（forgejo
222）、`gh`（release / alert 查询）、`uv`（编译锁）、`twine`（仅 `publish.sh`）。离线要求：
`changelog_*`、脱敏门、`version-check` 必须完全离线可用；`cron` 脚本断网时安静失败。

**脚本间**：

```
release.sh ──► changelog_guard.py, changelog_rotate.py(--check, --verify-history)
recut-public.py ──► publish-public.sh(--push/--no-tag/--check), changelog_guard.py, changelog_rotate.py,
                    pytest tests/{test_gates,test_paths,test_sanitization,test_recut_public}.py
pre-push ──► sanitize-patterns.sh        publish-public.sh ──► sanitize-patterns.sh
tests/test_sanitization.py ──► sanitize-patterns.sh      （同一份模式 = 同一份判据）
publish.sh ──► twine（独立，手工执行，不在 recut 链上）
```

**单一来源**：`sanitize-patterns.sh` 被三处读取；改模式只改它，再跑
`pytest tests/test_sanitization.py` + `bash scripts/publish-public.sh --check` 确认三处一致。

**外部状态**（不在仓库、不得假设存在）：`~/.hermes/scripts/`（cron 部署副本）、
`scripts/cron-repos.local.json`（gitignored）、`.hermes/internal-guide.md`（gitignored）、
`data/`（运行时库）。读它们必须「缺失即降级」，不写死路径。

## 4. 生命周期管理

**新增**（缺一项别合）：

1. 选类型；文件名：gate/publish 用动词短语，one-off 带日期 `*_YYYY_MM_DD.py`。
2. 顶部 docstring/头注释写：为什么存在（失败的实测）、入口、退出码、判据。
3. 登记到 §1（`tests/test_scripts_registry.py` 会核对）。
4. gate 必须有消费者（`release.sh`/`recut`/`pre-push`/tests）**和**一条回归测试。
5. 读外部状态的，docstring 里写明缺失时的行为。

**修改**（最容易出事）：

- 改 `sanitize-patterns.sh` → 三个消费者 + `test_sanitization.py` 一起验。
- 改 `pre-push` → `cp scripts/pre-push .git/hooks/pre-push`（否则改了仓库、真跑的还是旧的），
  再喂一次假 refs 核 exit code。
- 改 `changelog_rotate.py` 窗口规则 → 头部 `bytes=` 仍须等于实际字节（有门禁测试守着）。
- 改任何退出码 → 同步改 §2 表格：退出码是契约，不是实现细节。

**退役**（不删文件；删证据比留噪音贵）：

1. 文件首行加 `SUPERSEDED by <新文件> (vX.Y.Z)`，docstring 写清新旧差异。
2. 注册表状态改 `superseded`（测试会核对文件头确实有 `SUPERSEDED`）。
3. 新文件接管原判据，旧文件不再被任何 gate 引用。
4. 只有 `docs/CHANGELOG-archive.md` 已承载该轮结论后，才允许 `git rm`。

**one-off 约定**：跑完必须把**结论**写进 `CHANGELOG.md`（数字、判据、结论），脚本只留成因。
不要为了"以后可能用"把它改成通用脚本 —— 通用化是新建 `pipeline`/`gate`，不是给 one-off 加参数。

**为什么这么严**：本目录 30 个 tracked 文件里真正带判据的只有 6 个，其余靠文档活着。判据散落时，
一次「看起来发布成功」的切版能静默带走三份陈旧 requirements（2026-09-21 实测），或让 53 个开发
commit 永远推不出去（2026-10-26 实测）。
