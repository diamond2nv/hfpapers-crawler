# 生物医学诊断统计学方法 → 自研 AI 诊断/合规引擎 的可迁移方法映射表

- 检索日期：**2026-09-11**
- 检索源：Europe PMC REST API（`hfpapers.sources.EuropePmcSource`，覆盖 PubMed + PMC + 预印本）
- 检索工具：本仓库根（`hfpapers-crawler`，只读调用，未落库、未改代码；运行解释器为本仓库虚拟环境）
- 本文件性质：**证据驱动的映射表**。主表每一行的「出处」均为本轮真实检索命中的记录（DOI 由 Europe PMC 返回），未命中的方向统一列入第 ④ 节，不在主表中编造。

---

## ① 目的与范围

用户定位为「AI4S 多维度验证 / 诊断 / 合规 AI 引擎研发」。本表关心的**不是生物医学内容本体**，而是生物医学诊断准确性研究领域数十年沉淀下来的**统计与流程规范**，以及这些规范能否迁移到用户的引擎谱系（分层诊断栈 L0–L3、多源交叉验证、可信度分级、过程证据链）。

范围：
- **在范围内**：诊断准确性研究的报告规范、偏倚评估清单、参考标准问题、不确定性量化、性能/校准/效用度量、外部验证与证据分级。
- **不在范围内**：具体疾病的诊断结论；医学本体内容；与统计学/工程方法论无关的临床发现。

每条映射只回答四个问题：这个方法做什么 → 对应引擎的哪个环节 → 迁移的前提或代价 → 证据出处。

---

## ② 抓取方法与检索式

方法：
- 仅调用 `EuropePmcSource().search(query)`（`resultType=core`，含摘要）；每源每次检索间隔 ≥ 2.2 秒；每类 query 取回条数受 `page_size` 上限约束（本环境为 25）。
- 共执行 **2 轮、30 条检索式**，未调用 `paper_store` / `ensure_paper`，未写数据库。
- DOI 与标题均取自 Europe PMC 返回字段，未做二次编造。

**第 1 轮检索式与命中数（取回上限 25）**

| 检索式 | 命中 |
|---|---|
| `TITLE:"diagnostic accuracy" AND (TITLE:"reporting" OR TITLE:"guideline")` | 25 |
| `TITLE:"risk of bias" AND TITLE:"diagnostic"` | 18 |
| `ABSTRACT:"DeLong" AND ABSTRACT:"AUC"` | 25 |
| `ABSTRACT:"bootstrap" AND TITLE:"confidence interval" AND TITLE:"diagnostic"` | 2 |
| `ABSTRACT:"Bland-Altman"` | 25 |
| `ABSTRACT:"calibration" AND TITLE:"prediction model"` | 25 |
| `ABSTRACT:"TRIPOD"` | 25 |
| `ABSTRACT:"external validation" AND TITLE:"prediction model"` | 25 |
| `TITLE:"reference standard" AND TITLE:"diagnostic accuracy"` | 25 |
| `ABSTRACT:"likelihood ratio" AND TITLE:"diagnostic accuracy"` | 25 |
| `ABSTRACT:"PROBAST"` | 25 |
| `TITLE:"sample size" AND TITLE:"diagnostic accuracy"` | 13 |
| `ABSTRACT:"decision curve analysis" AND ABSTRACT:"prediction model"` | 25 |
| `ABSTRACT:"interobserver" AND TITLE:"diagnostic accuracy"` | 25 |
| `ABSTRACT:"spectrum bias" OR ABSTRACT:"verification bias"` | 25 |

**第 2 轮检索式与命中数（取回上限 25）**

| 检索式 | 命中 |
|---|---|
| `TITLE:"decision curve analysis"` | 25 |
| `TITLE:"statistical methods for assessing agreement"` | 4 |
| `TITLE:"DeLong"` | 25 |
| `TITLE:"calibration" AND (TITLE:"prognostic" OR TITLE:"clinical prediction")` | 24 |
| `TITLE:"PROBAST"` | 25 |
| `TITLE:"prediction model" AND TITLE:"validation" AND (TITLE:"framework" OR TITLE:"guidance")` | 4 |
| `TITLE:"likelihood ratio" AND ABSTRACT:"diagnostic test"` | 12 |
| `ABSTRACT:"kappa" AND TITLE:"agreement"` | 25 |
| `ABSTRACT:"net benefit" AND ABSTRACT:"decision curve"` | 25 |
| `ABSTRACT:"GRADE" AND TITLE:"diagnostic test accuracy"` | 25 |
| `TITLE:"STARD 2015"` | 18 |
| `TITLE:"QUADAS-2" OR TITLE:"QUADAS 2"` | 16 |
| `TITLE:"Transparent Reporting of a multivariable prediction model"` | 19 |
| `TITLE:"individual participant data" AND TITLE:"diagnostic accuracy"` | 14 |
| `TITLE:"bias" AND TITLE:"artificial intelligence" AND TITLE:"diagnostic"` | 4 |

> 注：`BiorxivSource` 的 API 是**日期区间式**（`/details/<server>/<start>/<end>/<cursor>`），无关键词检索能力；本轮方法学定向检索未使用该源（见第 ④ 节）。

---

## ③ 映射主表

列含义：**方法** | **出处（DOI + 标题）** | **方法做什么** | **对应引擎/环节** | **迁移前提或代价**

### A. 报告规范 / 条目化披露 → 过程证据合规层

| 方法 | 出处（DOI + 标题） | 方法做什么 | 对应引擎/环节 | 迁移前提或代价 |
|---|---|---|---|---|
| STARD 2015 条目化报告规范 | `10.1186/s41073-016-0014-7` — Updating standards for reporting diagnostic accuracy: the development of STARD 2015 | 通过 4 人项目组 + 14 人指导委员会 + 85 人 Delphi 问卷，把诊断准确性研究应披露的内容固定为条目清单（受试者招募、索引检验、参考标准、流程时点等） | 合规引擎的「过程证据披露层」：把「行为义务看过程证据」落成固定字段清单和检查项 | 清单为人类临床研究设计，需把「受试者 / 索引检验 / 参考标准」重新定义成语义等价的引擎概念；条目多，需要映射表 |
| STARD-AI（AI 专用扩展） | `10.1038/s41591-025-03953-8` — The STARD-AI reporting guideline for diagnostic accuracy studies using artificial intelligence | 在 STARD 2015 基础上增加 18 条 AI 特有（或修改）条目，要求披露数据集实践、AI 索引检验及其评估方式、算法偏倚与公平性 | 合规引擎针对 AI 组件的专用披露模板；直接对位「AI4S 验证引擎」的对外报告 | 条目面向临床诊断 AI，需裁剪到「验证/合规引擎」场景；公平性条目需要亚组数据，缺数据时无法满足 |
| STARD 依从性 meta-review | `10.1177/08465371261458187` — Reporting Completeness of Diagnostic Accuracy Studies: A Meta-Review of Investigations on Adherence to STARD 2015 | 汇总 14 篇综述、1115 项研究，量化 STARD 2015 的依从率并跨领域比较 | 合规引擎的「自评依从率」基准与 monitor 趋势监控 | 给出的是文献人群统计基准，不能直接当引擎自评阈值 |
| TRIPOD 声明 | `10.1038/bjc.2014.639` — Transparent reporting of a multivariable prediction model for individual prognosis or diagnosis (TRIPOD): the TRIPOD statement | 为预测模型的开发/验证/更新研究规定应报告的条目清单 | 合规引擎的模型生命周期披露清单（开发→验证→更新） | 面向多变量预测模型，需区分诊断用途 vs 预后用途 |
| TRIPOD+AI 依从性评估工具 | `10.1016/j.jclinepi.2025.112118` — Adherence to TRIPOD+AI guideline: an updated reporting assessment tool | 把 TRIPOD+AI 全文指南转成**可打分**的依从性评估工具 | 把「披露」从清单升级为可量化打分的合规检查表 | 打分仍需专家判断，自动化打分的准确性未在该文中验证 |
| TRIPOD-Code | `10.1186/s41512-025-00217-4` — Protocol for development of a reporting guideline (TRIPOD-Code) for code repositories associated with diagnostic and prognostic prediction model studies | 针对预测模型研究配套代码（预处理 / 开发 / 评估）的透明报告规范，用于管理代码仓库的过程证据 | 合规引擎的「代码级过程证据」与可复现性披露 | 目前处于 protocol 阶段，最终清单尚未发布，暂不能直接引用为成熟标准 |
| TRIPOD-AI / PROBAST-AI 制定流程 | `10.1136/bmjopen-2020-048008` — Protocol for development of a reporting guideline (TRIPOD-AI) and risk of bias tool (PROBAST-AI) for diagnostic and prognostic prediction model studies based on artificial intelligence | 描述如何用 5 阶段（系统综述 → Delphi → 共识会）为 AI/ML 预测模型制定报告指南与偏倚工具 | 「如何为 AI 组件定制合规标准」的方法论模板：可照搬其制定流程 | 描述的是**制定流程**而非最终清单，不能当成品标准使用 |

### B. 偏倚评估清单 → 审核 / 合规检查表

| 方法 | 出处（DOI + 标题） | 方法做什么 | 对应引擎/环节 | 迁移前提或代价 |
|---|---|---|---|---|
| QUADAS-2 / QUADAS-C 四域偏倚清单 | `10.7326/m21-2234` — QUADAS-C: A Tool for Assessing Risk of Bias in Comparative Diagnostic Accuracy Studies | 把偏倚评估固定为四域（患者选择 / 索引检验 / 参考标准 / 流程与时点），并扩展出比较研究版本（4 轮 Delphi + 24 位专家 + 试点） | 审核检查表（Reviewer / Auditor 角色）的检查维度骨架 | 四域为诊断准确性研究设计，映射到软件/引擎需为每一域重新定义信号问题 |
| QUAPAS（预后准确性扩展） | `10.7326/m22-0276` — QUAPAS: An Adaptation of the QUADAS-2 Tool to Assess Prognostic Accuracy Studies | 把 QUADAS-2 改造为预后准确性研究的偏倚工具，借用 QUIPS 与 PROBAST 的问题并配对到对应域 | 审核检查表在「前瞻/时序性」场景下的扩展版本 | 面向预后纵向研究（未来结局），与「当下诊断」语义不同，需判别用途后再选工具 |
| PROBAST 评分者间信度 | `10.1016/j.jclinepi.2025.111819` — Prediction model Risk Of Bias ASsessment Tool (PROBAST) shows high interrater reliability when scored by international experts on prediction modeling | 测量国际专家使用 PROBAST 打分时的一致性程度 | 验证「多评审者检查表」本身是否可靠（工具信度 ≠ 工具效度） | 结果是工具的信度证据，不能据此推断工具的效度或判定结论正确 |
| LLM 自动做 QUADAS-2 偏倚评估 | `10.3390/diagnostics15121451` — Risk of Bias Assessment of Diagnostic Accuracy Studies Using QUADAS 2 by Large Language Models | 4 个 LLM（含 2 个商用、1 个开源）对 10 篇研究做 QUADAS-2 的 110 个信号问题判定，与人类专家比对，平均正确率 72.95% | 合规/审核引擎的**自动化偏倚评估基线**：LLM 可作初筛，但未达专家水平 | 样本小（10 篇 / 110 问），正确率约 73%，不宜作最终判定；需配合人工复核 |
| TRIPOD+AI 与 PROBAST+AI 的参与式操作化 | `10.1177/11786329261477136` — Operationalising Inclusion for Participatory Design: Worked Examples for TRIPOD+AI & PROBAST+AI | 用 worked examples 说明如何把「包容性 / 公平性 / 利益相关者参与」操作化进 TRIPOD+AI 与 PROBAST+AI 框架 | 合规引擎的「公平性 + 利益相关者」维度设计 | 立场性/观点性论文，方法细节有限，只能作为设计参考而非方法锚 |
| 偏倚评估结果的加权呈现 | `10.1186/s13643-021-01744-z` — Application of weighting methods for presenting risk-of-bias assessments in systematic reviews of diagnostic test accuracy studies | 在系统综述中，如何按权重聚合与呈现逐研究偏倚评估结果 | 审核结果的聚合、加权与可视化 | 面向系统综述的整体证据合成，单引擎输出需裁剪权重规则 |

### C. 参考标准 / 金标准缺位处理 → 无 ground truth 的验证设计

| 方法 | 出处（DOI + 标题） | 方法做什么 | 对应引擎/环节 | 迁移前提或代价 |
|---|---|---|---|---|
| 参考标准质量对 AI 诊断准确性异质性的影响 | `10.1016/j.archger.2026.106241` — Impact of reference standard quality on the diagnostic accuracy of AI tools for MCI: A systematic review and meta-analysis | 系统综述 + 双变量随机效应模型 + 亚组分析，显示参考标准质量是 AI 工具诊断准确性异质性的来源之一 | 直接对应「无 ground truth / 参考标准缺位」时的**偏差来源识别**：把参考标准质量当作验证分层的显式变量 | 结论基于 8 项研究的经验证据，不是通用方法；只能作设计提示 |
| 独立参考标准的必要性 | `10.1177/01455613261488458` — Diagnostic Accuracy Requires an Independent Reference Standard in Local Allergic Rhinitis | 论证诊断准确性研究需要**独立于索引检验**的参考标准，否则构成循环论证 | 验证引擎的「参考标准独立性」硬约束设计 | 观点/评论性质，需与其他方法锚结合使用 |
| Verification bias 下的 CI 估计 | `10.1002/pst.70079` — Methodological Approaches for the Estimation of Confidence Intervals on Partial Youden Index Under Verification Bias | 当只有部分样本被金标准核实（partial verification），比较 full imputation / mean score imputation / IPW / 半参高效 四种偏差修正，并配 bootstrap 与 MOVER 构造 CI | 验证引擎在「部分核实 / 部分标签」场景下的偏差修正与区间输出 | 需要 MAR（随机缺失）假设；四种方法需实现与调参，且在不同 FPR 区间表现各异 |
| Verification bias 下 AUC 的修正区间 | `10.1177/09622802261455678` — Empirical likelihood inference for the area under the receiver operating characteristic (ROC) curve with verification biased data | 在 MAR 假设下，用 bootstrap 与经验似然两种方法为存在核实偏倚的 AUC 构造有偏修正置信区间（基于 Alonzo–Pepe 估计量） | 评分器 AUC 在标签不完整时的可信区间输出 | 依赖 MAR 假设；需实现经验似然求解，计算成本高于常规区间 |
| 无金标准下的似然比估计 | `10.1016/j.prevetmed.2006.02.007` — Likelihood ratio estimation without a gold standard: a case study evaluating a brucellosis c-ELISA in cattle and water buffalo of Trinidad | 在**完全没有金标准**时，用潜类/联合建模方式估计诊断似然比 | 无 ground truth 场景：用多个检验联合建模替代「金标准」 | 需要多个检验的联合观测，且依赖条件独立等强假设；假设不成立时估计不稳 |

### D. 不确定性量化 → 置信度与区间输出

| 方法 | 出处（DOI + 标题） | 方法做什么 | 对应引擎/环节 | 迁移前提或代价 |
|---|---|---|---|---|
| DeLong 检验（含缺失数据扩展） | `10.1002/sim.10172` — Extending the DeLong algorithm for comparing areas under correlated receiver operating characteristic curves with missing data | DeLong 1988 用来比较**相关 ROC 曲线**下的 AUC；本文指出常用实现会静默删除含缺失值的样本，并用秩化 + 混合模型扩展到缺失数据 | 置信度/显著性输出：比较两个评分器（或两个检测器）的 AUC 是否有差异 | 原实现遇缺失值会静默丢样本，需换用扩展实现；否则 AUC 比较可能有偏 |
| 固定特异度下灵敏度的自助法 CI | `10.1177/0962280214544313` — A better confidence interval for the sensitivity at a fixed level of specificity for diagnostic tests with continuous endpoints | 比较固定特异度下灵敏度区间的构造方法，提出基于 profile variance 的新区间，优于 BTII | 引擎区间输出的方法选型（连续评分场景） | 针对连续端点诊断检验；离散/分类评分需另行处理 |
| Bland-Altman 一致性分析 | `10.1016/s0140-6736(86)90837-8` — Statistical methods for assessing agreement between two methods of clinical measurement | 用差值均值 ± 一致性界限评估两种测量方法是否足够一致，明确指出用相关系数判断一致性会误导 | 多源评分/两套检测器之间的**一致性评估**；对应「多源交叉验证」中两源是否可互替 | 主要针对连续测量；分类/等级评分需改用 kappa 类一致性指标 |
| 评分者间一致性（kappa 及其陷阱） | `10.1111/vop.70208` — Challenges and Misinterpretations of Cohen's Kappa in Agreement Studies in Ophthalmology | 说明 Cohen's kappa 在类别不平衡（患病率悬殊）时会误导，给出使用与解释指引 | 多评审者 / 多智能体面板一致性的度量口径 | kappa 受患病率影响，需同时报告 prevalence 或改用平衡化的指标 |
| 诊断准确性研究中评分者间一致性的漏报 | `10.1097/dad.0000000000003334` — Underreporting of Interrater Agreement in Diagnostic Accuracy Studies of Immunohistochemistry in Dermatopathology: A Systematic Review | 系统综述 84 项研究，发现 87% 未报告任何评分者间一致性度量；提出复合指标 kappa-balanced score | 「多评审者面板」一致性的披露要求；提示引擎需把一致性作为必备输出维度 | 结论是「普遍漏报」这一现状，平衡化指标为新提出，验证有限 |

### E. 性能、校准与临床效用度量 → 多维度评分设计

| 方法 | 出处（DOI + 标题） | 方法做什么 | 对应引擎/环节 | 迁移前提或代价 |
|---|---|---|---|---|
| 校准测量与校准模型教程 | `10.1093/jamia/ocz228` — A tutorial on calibration measurements and calibration models for clinical prediction models | 区分 discrimination（区分度）与 calibration（校准度），给出校准度量与校准模型的 R 实现与适用场景 | 多维度评分中的「校准度」维度的具体实现 | 面向临床预测模型的「概率预测」；需把引擎的评分输出对位到概率语义 |
| Calibration slope 的语义 | `10.1016/j.jclinepi.2019.09.016` — Validation of clinical prediction models: what does the "calibration slope" really measure? | 追溯 calibration slope 的历史，用实例证明 slope=1 既可能对应好校准也可能对应差校准，该指标实际与区分度更相关 | 防止在多维度评分中把单一指标误当「校准」 | 结论是指标语义易被误用，需在引擎文档中显式固定每个指标的口径 |
| 校准漂移检测 | `10.1016/j.jbi.2020.103611` — Detection of calibration drift in clinical prediction models to inform model updating | 用在线随机梯度下降维护动态校准曲线，用自适应滑窗检测失校准，并给出可用于模型更新的数据窗口 | monitor 环节的漂移告警与「何时重训」触发 | 需要持续到达的真实标签流；在线更新引入状态管理与回滚成本 |
| 决策曲线分析（DCA） | `10.1515/dx-2025-0113` — Decision curve analysis explained | 用净获益（net benefit）在阈值维度评估临床效用，展示 AUC 相近的模型在效用上差异显著 | 多维度评分的「效用 / 代价权衡」维度，超越纯准确率 | 需要明确阈值与代价比；概念易被误解（该文专列常见误区） |
| 连续净获益 | `10.1186/s41512-026-00224-z` — The continuous net benefit: assessing the clinical utility of prediction models when informing a continuum of decisions | 把 DCA 扩展为对多个阈值 / 连续决策的净获益（重标度净获益曲线的加权面积） | 引擎在「多阈值 / 连续决策」下评估效用 | 新方法，外部验证与实现生态有限 |
| 诊断似然比作为衡量量 | `10.20506/rst.40.1.3226` — Diagnostic likelihood ratio - the next-generation of diagnostic test accuracy measurement | 用似然比（LR）替代敏/特，因为 LR 平衡真/假似然且**不依赖患病率**，可跨人群推广 | 多维度评分中「人群无关」指标的设计 | LR 忽略绝对准确性，两个不同准确性剖面可能同 LR，需配合敏/特或辅助判据 |
| 似然比置信区间的边界问题 | `10.1111/acem.13930` — Confidence at 100%: Characteristics of Likelihood Ratio Confidence Intervals in the Emergency Medicine Diagnostics Literature | 实证显示 100% 敏/特时 LR 的 CI 难以计算，导致文献更常漏报或使用欠妥方法 | 置信度输出在**极端值（0/1）**时的边界处理设计 | 该文描述问题与现状，未给出统一解法；极端值场景需专门处理 |
| 样本量估计（频数派） | `10.4103/2452-2473.357348` — User's guide to sample size estimation in diagnostic accuracy studies | 针对二分结局诊断检验，给出样本量估计流程、实用表格与在线计算器 | 验证引擎的「取多少样本 / 积累多少证据才够」预算设计 | 需要预定义精度目标；面向单次研究的横断设计 |
| 样本量估计（贝叶斯 assurance） | `10.1002/sim.9393` — Bayesian sample size determination for diagnostic accuracy studies | 利用分析有效性阶段的信息，用 assurance 与后验概率区间目标宽度确定样本量，并做先验敏感性分析与先验-数据冲突检验 | 预算设计：把前期（小规模）证据显式纳入样本量计算 | 需要设定先验分布；先验与数据冲突时需要额外处置逻辑 |

### F. 外部验证分层与证据分级 → 跨源交叉验证等级 / 可信度分级

| 方法 | 出处（DOI + 标题） | 方法做什么 | 对应引擎/环节 | 迁移前提或代价 |
|---|---|---|---|---|
| 外部验证的报告现状 | `10.1016/j.jclinepi.2026.112460` — Reporting of external validation studies needs improvement: a systematic review of reporting in oncology prediction model studies | 横断面调查某时段肿瘤预测模型研究，统计包含外部验证（时间外/站点外）的比例与报告完整度 | 跨源交叉验证等级：为「内部验证 / 时间外 / 站点外」分级提供现实基线（外部验证稀缺且报告不足） | 描述现状而非方法；不能直接作为「外部验证怎么做」的操作指南 |
| 个体参与者数据（IPD）meta 分析 | `10.1148/rycan.240015` — Individual Participant Data Meta-Analyses for Diagnostic Accuracy Research: Challenges and Lessons Learned from the LI-RADS IPD Group | 用个体级数据跨研究合并诊断准确性，处理研究间异质性（含预测区域等） | 多源聚合验证：跨站点 / 跨数据集的分层合并方法 | 需要各来源共享个体级数据，涉及隐私、整合与治理成本 |
| GRADE 在诊断准确性证据体的确定性分级 | `10.1017/rsm.2025.10047` — Developing an approach for assigning GRADE levels in a systematic overview of reviews of diagnostic test accuracy using general principles identified from current GRADE guidelines: A case study | 把 GRADE 的各个域应用到「综述的综述」这一复杂证据体，产出「一般原则式」的分级流程 | 可信度分级（引擎的 🟢 / 🟡 / 🔴 等级）的国际方法学依据 | GRADE 面向整条证据体综述，需裁剪为「单引擎/单条输出」的分级规则 |
| 预后模型校准证据的确定性（GRADE concept paper 2） | `10.1016/j.jclinepi.2021.11.024` — GRADE concept paper 2: Concepts for judging certainty on the calibration of prognostic models in a body of validation studies | 提出判断「预后模型校准表现」证据确定性的核心概念（区分两种推断形式），用于验证研究的系统综述 | 可信度分级在「校准度」这一维度上的判定依据 | 面向预后模型的校准证据体；迁移到诊断/引擎评分需重定义推断对象 |

---

## ④ 未能取到证据的方向

以下方向本轮**未取到可追溯的证据**，故未写入主表：

1. **bioRxiv / medRxiv 源的方法学证据**：该 API 只支持日期区间检索，无关键词检索，本轮方法学定向检索未使用，因此未从预印本源取到任何方法学锚。
2. **软件技术架构层面的生物医学方法论文**：如医学影像数据管道（DICOM / HDF5）、实验/模型版本管理、推理服务架构、MLOps 监控架构等。本轮的 Europe PMC 关键词检索式未覆盖，**未取到证据**。
3. **AI 医疗器械合规监管框架**：如 SaMD 分类、软件全生命周期法规、上市后监测等监管性文件。本轮未检索，**未取到证据**。
4. **公平性 / 亚组差异的专项定量方法**：仅间接取到 STARD-AI 对「算法偏倚与公平性」的披露要求，以及 `10.1117/1.jmi.10.6.061108`（Validating racial and ethnic non-bias of AI decision support for diagnostic breast ultrasound evaluation）。**专项公平性度量方法论文未取到充分证据**，故未单列进主表。
5. **时序外验证 / 站点外验证的操作性方法学**（而非现状调查）：主表 F 组取到的是「报告现状」与「IPD 合并」，**专门论述分层验证设计的操作性方法论文本轮未取到**。
6. **多智能体面板 / 对抗评审在诊断评估中的方法学**：本轮检索式未面向该方向，**未取到证据**。

---

## ⑤ 局限说明

1. **检索方式**：Europe PMC 为关键词检索，取回条数受 `page_size`（本环境 25）上限约束；`bootstrap_ci` 类窄检索式仅 2 条命中，说明语法收窄过快。主表条目是「检索式命中集合中的择优」，不是系统性综述。
2. **证据强度分级**：主表中既有原始方法学论文（如 Bland-Altman 1986、TRIPOD 2015）、也有方法学扩展（DeLong 缺失数据扩展）、还有描述现状的系统综述/横断面调查。**三者的证据类型不同**——最后者只能支撑「现状/风险」判断，不能支撑「某方法有效」的结论。引用时须区分。
3. **时点**：全部命中为截至 2026-09-11 的 Europe PMC 记录；预印本记录可能在后续版本中变更。
4. **映射的置信度**：「方法做什么」「出处」为文献事实（可回溯 DOI）；「对应到哪个引擎/环节」与「迁移前提或代价」是**本表的推断性映射**，未经用户引擎的实证验证。落地前应逐条验证。
5. **未做落库**：本轮未调用数据库写入接口，未修改 `hfpapers/` 下任何代码，未运行测试，未做 git 提交。
6. **脱敏**：本文件已排除真实个人姓名、内网地址、机器名与个人邮箱（仓库存在公开远端）。
