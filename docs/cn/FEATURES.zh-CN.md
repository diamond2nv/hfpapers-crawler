# 功能详解

> 本项目五项核心能力的浓缩版；[`README.md`](../../README.md) 只保留
> 五点摘要，详细说明在本页，并给出参考文档链接。

## 1. 发现

- **多源注册表** —— arXiv API、OpenReview、Papers-with-Code、HuggingFace Papers，以及生物医学适配器（Europe PMC、bioRxiv/medRxiv）都实现同一个两成员契约（`PaperSource`：`name` + `search`），注册在同一张表 `SOURCE_CLASSES` 中。
- **社区引导扩展** —— `hfpclawer graph expand-hub --community`：种子 → 其 Louvain 社区 → 社区 hub，忠实映射 x-algorithm 的 SimClusters 思路，用于"跟这篇像的论文"式主题探索。
- **相关性打分与"不丢数据"的去重** —— 关键词分类 + 跨源去重键 `arxiv_id → doi → title`；完全无可用键的记录也会保留，而不是被静默丢弃。

详见：[`docs/USAGE.md`](../USAGE.md) · [`docs/ARCHITECTURE.md`](../ARCHITECTURE.md)

## 2. 验证

- **显式状态机** —— 每篇论文带 `pending → verified / stale / suspect`，由已存证据派生，而非 LLM 的判断。
- **冲突显性化** —— DOI 解析出的 arXiv id 与记录不一致时标为 **suspect**；suspect 记录既不计入 verified，也不进训练池。
- **符号化、0-LLM 检查** —— 检查是确定性的，不会让 LLM 去"判断论文是否真实"。

详见：[`docs/paper_store.md`](../paper_store.md) · [`docs/use/verify-guide.md`](../use/verify-guide.md)

## 3. 推荐

- **第一方信号** —— 查询历史 × 文本相似度 × 相关性 × 验证状态门禁，全部由本地库计算；无需外部服务，也无需注册。
- **仓库级画像** —— 每个仓库都是自己的虚拟用户：`hfpclawer init` 生成 `REPO_USER.md`，其 v2 的 `accepts/rejects` 块即显式反馈（`scope: topic-exclusion` 过滤候选，`scope: self-constraint` 只记录选择不过滤）。
- **学习层可选且可解释** —— `hfpclawer rank train`（lightgbm → 原生模型）用 JSONL 审计轨迹训练，以特征重要性作解释；启发式层仍是 0-token 默认。
- **可审计轨迹与干净正例池** —— 每次扩展都可输出审计轨迹；`hfpclawer pool` 从本地无标注来源累积分层弱标签；append-only 且 gitignore，无任何遥测离开本机。
- **Zotero 可选** —— `hfpclawer zotero sync-back` 通过学术契约拉取 Favor 条目（网页/报告先被剔除），把命中论文标为 `favorited`；不装 Zotero 也不影响任何功能。

详见：[`README.md`](../../README.md) · [`docs/ROADMAP.md`](../ROADMAP.md)

## 4. 配置与数据源

- **公开配置可发布** —— 被跟踪的 `config.yaml` 只含结构与占位；真实姓名、ORCID、检索式放在被 gitignore 的 `config.local.yaml`，深度合并覆盖（`search.biomed_queries: []` 是声明的槽位）。
- **注册不等于启用** —— 只有键在 `search.enabled` 中时源才运行；新增源不会改变既有行为。
- **先验证字段形状再实现** —— Europe PMC 必须带 `resultType=core`，否则摘要为空；bioRxiv/medRxiv 只有日期区间 API，关键词过滤放在入库侧。
- **共享重试策略** —— 所有源统一走 `PaperSource._get()`，遵循 `anti_crawl.max_retries` / `retry_http_codes` / `retry_delay_base`；单次瞬态 503 不再丢一整批。

详见：[`docs/ARCHITECTURE.md`](../ARCHITECTURE.md) · [`DEPLOY.md`](../../DEPLOY.md)

## 5. Agent 优先

- **CLI 优先，MCP 次之** —— 每项能力都是带文档的子命令，输出可机械校验；MCP server 默认只暴露只读核心，重操作隐藏以省 token。
- **0-token 监控** —— `hfpclawer check-new` 与自身上次输出比较即 cron 门禁：输出稳定 = "无变化，不要唤醒 LLM"。
- **能在恶劣网络下存活的传输** —— TCP → QUIC → browser-hint 阶梯、可续传、每次抓取记 sha256 到 `data/download_audit.jsonl`。
- **门禁而非纪律** —— `scripts/pre-push` 拒绝未脱敏提交与版本/tag 不一致；`scripts/release.sh` 拒绝条目缺失、窗口超预算或丢条目的发布；`scripts/doc_audit.py` 校验文档提到的路径与命令真实存在。

详见：[`AGENTS.md`](../../AGENTS.md) · [`docs/DEVELOPMENT.md`](../DEVELOPMENT.md) · [`docs/CHANGELOG.md`](../CHANGELOG.md)

## 刻意不做的事

- 云端同步／托管存储（本地单点数据）；论文笔记与标注（属于 wiki 层）；L6 形式化验证（仅预留接口）。详见 [`ROADMAP.md`](../ROADMAP.md)。
