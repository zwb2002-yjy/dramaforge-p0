# Release Gate Board

**状态：LIVE / 发布证据看板，不定义产品合同**

**最近复核：2026-08-21**

本看板执行 [`../current/01-产品与发布契约.md`](../current/01-产品与发布契约.md)、[`../current/03-质量与验证体系.md`](../current/03-质量与验证体系.md) 和 [`../current/04-执行路线图.md`](../current/04-执行路线图.md)。架构证明另见 [`../current/02-运行时与领域架构.md`](../current/02-运行时与领域架构.md#14-架构确认表)。

`PASS` 必须绑定一个干净候选 commit 和要求的证据类型。Mock、Spy、旧 P0、其他 commit 或口头结论不能替代真实 Provider、目标用户、离线硬件和安装证据。脱敏证据写入 `tmp/p0-evidence/<source-commit>/`；任何真实付费请求前必须执行 [`real-provider-evidence-preflight.md`](real-provider-evidence-preflight.md) 并获得单次书面授权。

## 当前候选边界

| 字段 | 当前事实 |
|---|---|
| 运行候选 | `9665773ba85bc1d36c4646352681ea690c8a1ed4` (`dev`) |
| 当前候选 | `9665773`；运行中的 API、Dispatcher、两个 Worker 与 Frontend 同源，数据库 head `20260820_0029`；两个 Worker 共用同一 Backend 镜像；PostgreSQL、Redis、MinIO、LiteLLM 与数据卷未重建 |
| 自动化基线 | 当前候选后端全量 `662 passed / 16 skipped`、前端 `57 passed`、Chromium `11/11`、typecheck/build、Ruff/mypy 通过；同源 Docker Compose 栈健康 |
| 真实证据 | 一个 Agnes 真实视频镜头被 Q3 人工拒绝；`2026-08-20` 单次、`0.01 CNY` 上限 Agnes 图片 v2 `image_i2i` 账号 Probe 通过，Binding 已 account-verified；`2026-08-21` 完成新授权下真实 Director TRIAL：t2i character_reference 成功、i2i keyframe 成功（Artifact + EffectiveRequest + TranslationReport + ProviderOperation unified-v1 已持久化）、i2v video 被 Agnes 拒绝（503 PROVIDER_CREATE_FAILED）、provider 未报告成本故账本 consumed=0；identity_review=needs_human；完整试拍、修复、全片或用户测试仍无 |
| 历史边界 | `0cb923f` 曾关闭 A2，但不是当前候选；只作为回归目标，不计入当前 HEAD 发布通过数 |

## Gate A：核心体验

| ID | 要求 | 必须证据 | 当前状态 | 下一动作 |
|---|---|---|---|---|
| A1 | 三入口、四阶段、四确认和变更预览 | 当前候选的真实后端浏览器 E2E | `PARTIAL` | Visual 2.0 canonical 路由和 Mock API E2E 已通过；补 authenticated live-stack |
| A2 | 快速/专业模式共享同一事实源 | 双模式读取同一版本、批次、预算和血缘 | `PARTIAL` | 在当前候选复现历史 A2 场景 |
| A3 | 试拍、生产和修复费用分别授权 | 真实请求、Reservation、ProviderOperation 和实际费用 | `PARTIAL` | `5783e6b` 下完成新授权 $12 TRIAL：Reservation `63b5dfb7`、ProviderOperation `unified-v1` 已持久化；真实 t2i+i2i 成功但 provider 未报告成本（cost_status=not_reported，账本 consumed=0），需 provider 账单/成本确认；video i2v 被拒（503） |
| A4 | Canonical 和必需参数进入有效请求 | Spy + 真实 EffectiveRequest/TranslationReport | `PARTIAL` | `5783e6b` 下真实 Unified Director I2I：compiled_request `image.i2i` 携带 reference_artifact_ids=`64ad1657` + SHA-256、size=1K（frozen manifest 变换）、aspect=9:16；TranslationReport 已持久化（无 dropped_options）；identity_review=needs_human 需人工复核 |
| A5 | 代表镜头真实暴露风险或支持继续 | 试拍 Artifact、Q0–Q6、限制和用户决定 | `PARTIAL` | 产品内质量报告已把 video 503、缺失 video/composite 和 MinIO 字幕竞态列为不可覆盖硬阻断；需修复后完成用户验收 |
| A6 | 一个失败镜头被局部修复 | 新旧 NodeRun、复用 Artifact、额外授权和费用 | `PARTIAL` | 真实 RepairPlan `0a056f2c…` 已生成并选中 10 USD 视频单点方案；独立授权后执行，并核对仅重跑 video 与三个下游 |
| A7 | 15–30 秒中文对白作品和四项交付 | 同一候选的多镜头真实全链 | `OPEN` | 完成 1 主角、3 镜头黄金样本 |
| A8 | 三名目标用户无人代操作完成 | 三份脱敏用户记录 | `OPEN` | A7 稳定后安排三次测试 |
| A9 | 至少两人愿意保存、展示或继续创作 | A8 对应的结束问题原话 | `OPEN` | 与 A8 同步收集 |

## Quality Gate

| ID | 要求 | 当前状态 | 下一动作 |
|---|---|---|---|
| Q0 | 授权、能力、许可和参考有效 | `PARTIAL` | 真实 TRIAL 使用冻结 Binding/Manifest 与 12 USD 上限；旧授权不允许付费重试，下一次 G5 必须重新明确授权；Binding 仍待真实质量验收后提升 quality gate |
| Q1 | 有效请求完整 | `PARTIAL` | 真实 I2I 已证明 Canonical ID/SHA-256、1K、9:16 和无 dropped options；视频创建被 503 拒绝，尚无远端任务与输出 Artifact |
| Q2 | 文件、尺寸、时长、音轨、黑帧和静音检查 | `OPEN` | 对试拍和交付 Artifact 执行确定性检查 |
| Q3 | 人物、外观、肢体和时序证据 | `PARTIAL` | 已有一条拒绝记录；补项目级 Canonical 和产品内人工结论 |
| Q4 | 声音、说话人、口型和表演 | `OPEN` | 明确 post-dub 无 lip-sync 引擎并完成试听/观察证据 |
| Q5 | 叙事、对白和连续性 | `OPEN` | 对黄金样本逐镜复核 |
| Q6 | 用户验收和主观覆盖 | `OPEN` | 通过产品流程记录，不改写自动结果 |
| Q7 | 身份、声音/口型、叙事三类修复演练 | `OPEN` | 先以真实失败证据生成可执行修复方案 |
| Q8 | 模型、权重、声音和字体许可 | `OPEN` | 完成第三方资源清单和负责人签字 |

## Gate B：离线生产栈

| ID | 要求 | 当前状态 | 下一动作 |
|---|---|---|---|
| B1 | 一套离线栈在声明硬件完成真实作品 | `OPEN` | 云端 Gate A 稳定后冻结唯一离线组合 |
| B2 | 离线质量、能力和硬件限制明确 | `OPEN` | 只发布实测结果，不推断与云模型等价 |

## Gate C：安装与发布

| ID | 要求 | 当前状态 | 下一动作 |
|---|---|---|---|
| C1 | Linux/AIOS 一等安装、恢复和真实链 | `OPEN` | Gate A 候选冻结后实机执行 |
| C2 | Windows 11 一等安装、恢复和真实链 | `PARTIAL` | 旧安装器证据存在；当前候选需重验完整作品 |
| C3 | macOS 二等云 Provider 路径 | `OPEN` | 明确不承诺同等本地视频能力 |
| C4 | 安全、隐私、SBOM 和第三方供应链 | `PARTIAL` | 单 Owner/基础安全已有代码；当前候选需完整签字 |
| C5 | 所有发布证据绑定同一干净 commit | `OPEN` | A–C 关闭后冻结 RC |

## 状态变更记录

每次状态变化追加：日期、Gate ID、前后状态、完整 commit、证据目录、复核角色和已知限制。失败记录不得删除或改写。旧看板历史可从 Git 历史查询，不继续复制到当前入口。

| 日期 | Gate ID | 状态变化 | 完整 commit | 证据目录 | 复核角色 | 说明 |
|---|---|---|---|---|---|---|
| 2026-08-21 | A3, A4 | PARTIAL -> PARTIAL（证据推进） | `5783e6b141d5d67f3625e442aae9385cee917482` | `tmp/p0-evidence/5783e6b141d5d67f3625e442aae9385cee917482/real-provider/` | run_operator | Authorization `auth-g4-trial-2026-08-21-001`; scope trial; cost 真实 t2i+i2i 成功（provider 未报告成本，账本 consumed=0）；video i2v 被 Agnes 拒（503 PROVIDER_CREATE_FAILED）；result pass（核心 I2I 成功）+ blocked（video）；known limits: provider 成本未确认、video 未生成、identity_review=needs_human、subtitle 失败为 MinIO bucket 竞态 |
| 2026-08-21 | A5 | OPEN -> PARTIAL | `8e3c30738cbc57c15afdf6c604b7879465f53133` | 产品内 QualityReport + DOM 断言 | run_operator | 10 个试拍节点全部终止并生成质量报告；硬阻断不可接受；修复 MinIO bucket 并发、Canonical/Keyframe 误选和工作区 Provider 上下文竞态，未触发新的 Provider 请求 |
| 2026-08-21 | A6 | OPEN -> PARTIAL | `9665773ba85bc1d36c4646352681ea690c8a1ed4` | `tmp/p0-evidence/9665773ba85bc1d36c4646352681ea690c8a1ed4/g5-repair-preflight/decision.json` + RepairPlan `0a056f2c-a6b7-4e64-bc48-2873f2690f1e` + 产品 DOM | run_operator | 基于真实 503 与硬阻断生成三个结构化修复方案；UI 中选中 10 USD 视频单点方案，失效范围为 video、video_drift_review、composite、continuity_review；当前 awaiting_repair_authorization，未创建新 Authorization、Repair Batch 或 ProviderOperation |
