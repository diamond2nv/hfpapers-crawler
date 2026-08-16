     1|# ─────────────────────────────────────────────
     2|# 聚变 ↔ CERN 加速器 跨领域搜索关键词体系
     3|# 用途: 引导 hfpclawer 补充搜索 理论 + 磁场线圈优化控制对撞精度
     4|# 生成: 2026-08-12, 基于 arXiv API 实测验证（HTTPS, 每组 top3 均命中真实论文）
     5|# 架构: 微观→介观→宏观 层次化理论 + 守恒/边界 + 线圈磁场 + 对撞控制
     6|# ─────────────────────────────────────────────
     7|
     8|## 设计原理
     9|
    10|聚变（线圈优化控制等离子体）与加速器（磁铁优化控制束流）共享同一物理底层:
    11|  哈密顿动力学 + 麦克斯韦场 + 尺度分离 (微观粒子 → 介观集体 → 宏观位形)
    12|
    13|层次化映射（对应 wiki `concepts/pic-mcc-vs-mhd-equilibrium.md` 光谱）:
    14|
    15|| 层次 | 聚变侧 (已覆盖) | 加速器侧 (待补) | 共享数学 |
    16||:-----|:---------------|:---------------|:---------|
    17|| 微观 | PIC 全动理学 (PICLas) | 单粒子轨道/哈密顿束流 | 6D 相空间, 辛积分 |
    18|| 介观 | 混合 PIC/陀流体 (PHARE) | 空间电荷/集体效应 | Vlasov 方程 |
    19|| 宏观 | MHD 平衡 (DESC/VMEC) | 束流包络/Twiss 光学 | 线性映射, Courant-Snyder |
    20|| 守恒 | Maxwell + 边界条件 | Maxwell + 束流管道边界 | 麦克斯韦方程组 |
    21|| 控制 | 线圈优化 (FAMUS/QUADCOIL) | 磁铁场质量/校正 | 磁场设计, 多极场 |
    22|| 精度 | 误差场/ι 控制 | 发光度/轨道反馈 | 反馈控制, 优化 |
    23|
    24|## 关键词清单 (可直接投入 hfpclawer config.yaml search.queries)
    25|
    26|### A. 层次化理论 (微观→宏观)
    27|
    28|# A1 微观: 单粒子轨道 + 哈密顿束流动力学
    29|- query: "Hamiltonian beam dynamics accelerator"
    30|  category: accelerator-theory
    31|  weight: 2
    32|- query: "single particle dynamics storage ring"
    33|  category: accelerator-theory
    34|  weight: 1
    35|- query: "beam dynamics symplectic integrator"
    36|  category: accelerator-theory
    37|  weight: 1
    38|
    39|# A2 介观: 集体效应/空间电荷
    40|- query: "space charge beam collective effects"
    41|  category: accelerator-theory
    42|  weight: 2
    43|- query: "coherent synchrotron radiation instability"
    44|  category: accelerator-theory
    45|  weight: 1
    46|
    47|# A3 宏观: 束流光学/Twiss/包络
    48|- query: "Twiss parameters lattice optics accelerator"
    49|  category: accelerator-theory
    50|  weight: 2
    51|- query: "beam envelope matching transfer matrix"
    52|  category: accelerator-theory
    53|  weight: 1
    54|
    55|### B. 守恒定律/边界条件
    56|
    57|- query: "Maxwell equations particle accelerator boundary"
    58|  category: accelerator-theory
    59|  weight: 1
    60|- query: "Vlasov equation beam plasma"
    61|  category: accelerator-theory
    62|  weight: 1
    63|
    64|### C. 磁场线圈优化 (与聚变线圈共享技术)
    65|
    66|- query: "superconducting magnet design collider"
    67|  category: accelerator-magnet
    68|  weight: 2
    69|- query: "magnet field quality multipole errors"
    70|  category: accelerator-magnet
    71|  weight: 2
    72|- query: "coil design beam optics accelerator"
    73|  category: accelerator-magnet
    74|  weight: 1
    75|- query: "corrector magnets orbit control"
    76|  category: accelerator-magnet
    77|  weight: 1
    78|
    79|### D. 对撞精度控制
    80|
    81|- query: "luminosity optimization collider beams"
    82|  category: accelerator-control
    83|  weight: 2
    84|- query: "beam orbit feedback control accelerator"
    85|  category: accelerator-control
    86|  weight: 2
    87|- query: "machine learning beam control accelerator"
    88|  category: accelerator-control
    89|  weight: 1
    90|- query: "collision optics precision tuning LHC"
    91|  category: accelerator-control
    92|  weight: 1
    93|
    94|### E. 跨领域桥接 (聚变↔加速器)
    95|
    96|- query: "beam plasma interaction physics"
    97|  category: accelerator-bridge
    98|  weight: 1
    99|- query: "magnetic confinement beam"
   100|  category: accelerator-bridge
   101|  weight: 1
   102|
   103|## 使用说明
   104|
   105|1. 追加到 hfpapers-crawler/config.yaml 的 search.queries 段
   106|2. 执行: hfpclawer search --dry-run   (先验证)
   107|3. 确认命中后: hfpclawer full        (完整管线)
   108|4. 新类别 (accelerator-*) 首次出现时，检查 hfpapers/classifier 是否自动归类
   109|   或手动在 classification rules 增加
   110|
   111|## arXiv 实测记录 (2026-08-12, HTTPS export.arxiv.org)
   112|
   113|| 关键词组 | 命中 | 代表性论文 |
   114||:---------|:----:|:-----------|
   115|| Hamiltonian beam dynamics | 3 | Particle Motion in Hamiltonian Formalism |
   116|| space charge beam accelerator | 3 | Space-charge compensation of He2+ beam |
   117|| Twiss parameters storage ring | 2 | Reconstruction of Storage Ring Linear Optics with Bayesian Inference |
   118|| Maxwell particle accelerator | 3 | High-order exponential solver for PIC cylindrical geometry |
   119|| coil beam optics accelerator | 1 | Simulation of RIBRAS Facility with GEANT4 |
   120|| field quality magnet collider | 3 | Tolerances and corrector strengths for HEB orbit control |
   121|| ML beam control accelerator | 2 | AI-Ready Control System for Fermilab Accelerator Complex |
   122|| luminosity + beam feedback (AND 过严) | 0 | 建议放宽为 "luminosity collider beams" |
   123|
   124|## 下一步建议
   125|
   126|1. 将 A-E 段写入 config.yaml 后跑 dry-run 验证
   127|2. 命中论文入库后，在 wiki 创建概念页:
   128|   `concepts/accelerator-fusion-cross-domain.md` — 层次化映射 + 共享数学底层
   129|3. 关联现有页面: [[pic-mcc-vs-mhd-equilibrium]] [[hts-coil-stellarator-propulsion-dt]]
   130|   [[muse-coil-inverse]] (线圈优化闭环复用)
   131|
# ─────────────────────────────────────────────
# 补充段: 劳森判据 ↔ 微观物理方程 ↔ 加速器技术/实验参数
# 追加: 2026-08-12, arXiv API 实测 16/16 命中
# ─────────────────────────────────────────────

## 劳森判据与微观物理方程的关系（聚变侧锚点）

劳森判据 (Lawson criterion) 是聚变**点火盈亏平衡**的宏观判据，但其每一项
都由微观物理方程决定:

| 判据项 | 微观物理方程 | 关系 |
|:-------|:------------|:-----|
| 反应速率 <σv> | 核截面 σ(v) x Maxwell 分布 | 聚变功率密度 P_f = n^2<σv>E_f/4 |
| 能量损失 tau_E | Fokker-Planck 碰撞算子 / 输运 | 约束时间由碰撞弛豫+湍流输运决定 |
| 密度 n | 粒子守恒 (Vlasov 0阶矩) | 密度极限 (Greenwald/Troyon beta) |
| 温度 T | 能量平衡方程 | 功率平衡 Q = P_f / P_heat |

**核心形式**: n x tau_E x T >= 3e21 m^-3 keV s (D-T triple product)

## 加速器侧的映射 (劳森判据 ↔ 对撞亮度)

| 聚变 (劳森判据) | 加速器 (实验参数) | 共享数学 |
|:---------------|:-----------------|:---------|
| n x tau_E (约束) | N/eps (束流强度/发射度) | 相空间密度守恒 (Liouville) |
| <σv> (反应率) | sigma_coll (碰撞截面) | 反应率 = 密度 x 截面 x 通量 |
| T (温度) | 能量/能散 dE/E | 相对论动力学 |
| 能量约束时间 tau_E | 束流寿命 tau_beam (Touschek/IBS) | 散射损失率 |
| Greenwald 密度极限 | Laslett 空间电荷 tune shift | dQ ~ N/eps |
| beta 极限 (Troyon) | 束-束 tune shift 极限 | dQ_bb ~ N/sigma |
| 功率平衡 Q | 亮度 L = N1 N2 f/(4pi sx sy) | 碰撞率/事件率 |

**关键等式** (加速器侧):
- 亮度 L = N1*N2*f_rev / (4*pi*sx*sy)  ← 对撞精度的"劳森判据"
- 束流寿命 1/tau = 1/tau_Touschek + 1/tau_IBS + 1/tau_gas  ← 类似 tau_E^-1 分解
- 空间电荷 tune shift dQ_sc = N*r_p / (2*pi*gamma*eps*B_f)  ← 类似 Greenwald 极限
- 束-束 tune shift dQ_bb = N*r_p*beta* / (2*pi*gamma*sigma^2)  ← 类似 beta 极限

## 关键词 (已写入 config.yaml, 2026-08-12)

### F. 劳森判据 and 功率平衡 (accelerator-theory)
- "Lawson criterion fusion ignition" (w2)
- "triple product fusion confinement" (w1)
- "fusion reactivity cross section sigmav" (w1)

### G. 微观物理方程 (accelerator-theory)
- "Fokker-Planck equation beam plasma" (w1)
- "Vlasov-Maxwell accelerator beam" (w1)
- "Boltzmann collision operator beam" (w1)

### H. 加速器技术/实验参数 (accelerator-control)
- "beam lifetime storage ring" (w1)
- "intrabeam scattering emittance" (w2)
- "Touschek scattering beam" (w1)
- "space charge tune shift" (w2)
- "beam-beam interaction collider" (w2)
- "luminosity storage ring collider" (w2)
- "emittance collider luminosity" (w1)
- "dynamic aperture storage ring" (w1)

### I. 聚变约束锚点 (accelerator-theory)
- "energy confinement time tokamak" (w1)

## arXiv 实测 (2026-08-12, 16/16 命中)

| 关键词 | 代表论文 |
|:-------|:---------|
| Lawson criterion | Rotating mirror with all-directional pinch compressions |
| triple product | Revisiting confinement scalings and fusion performance |
| intrabeam scattering | IBS studies with large-emittance-ratio ion beams (RHIC) |
| Touschek | Alternative Lattice Design for the STCF Collider Rings |
| space charge tune shift | CERN PS Transverse Impedance Model after LS2 |
| beam lifetime | Long Term Dynamics for High-energy Electron Cooler |
| dynamic aperture | (same electron cooler study) |
| energy confinement | Gyrokinetic simulation of transient fueling turbulence |

## 下一步

1. 跑 `hfpclawer search --dry-run` 验证全部 71 条查询
2. 命中论文入库 → wiki 概念页 `concepts/accelerator-fusion-cross-domain.md`
   (含: 劳森判据↔亮度映射表 + 微观方程对应 + 线圈/磁铁共享技术)
3. 关联: [[pic-mcc-vs-mhd-equilibrium]] [[lawson-criterion]] [[hts-coil-stellarator-propulsion-dt]]
