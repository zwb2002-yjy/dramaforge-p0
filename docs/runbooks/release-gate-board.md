# Release Gate Board

**状态：LIVE / 发布证据看板，不定义产品合同**

**最近复核：2026-08-21**

本看板执行 [`../current/01-产品与发布契约.md`](../current/01-产品与发布契约.md)、[`../current/03-质量与验证体系.md`](../current/03-质量与验证体系.md) 和 [`../current/04-执行路线图.md`](../current/04-执行路线图.md)。架构证明另见 [`../current/02-运行时与领域架构.md`](../current/02-运行时与领域架构.md#14-架构确认表)。

`PASS` 必须绑定一个干净候选 commit 和要求的证据类型。Mock、Spy、旧 P0、其他 commit 或口头结论不能替代真实 Provider、目标用户、离线硬件和安装证据。脱敏证据写入 `tmp/p0-evidence/<source-commit>/`；任何真实付费请求前必须执行 [`real-provider-evidence-preflight.md`](real-provider-evidence-preflight.md) 并获得单次书面授权。

## 当前候选边界

| 字段 | 当前事实 |
|---|---|
| 运行候选 | `faee665c1d53dd6c6f48064fbb2a6b6887efd91d` (`dev`) |
| 当前候选 | `faee665`；运行中的 API、Dispatcher、两个 Worker 与 Frontend 同源健康，数据库 head `20260821_0031`；两个 Worker 共用同一 Backend 镜像；PostgreSQL、Redis、MinIO、LiteLLM 与数据卷未重建 |
| 自动化基线 | 当前候选后端全量 `670 passed / 16 skipped`、前端 `60 passed`、Chromium `11/11`、typecheck/build、Ruff/mypy 通过；同源 Docker Compose 栈健康 |
| 真实证据 | Director Workflow `ade7a0b0…` 完成真实 t2i、I2I、I2V、同远端 ID Worker 恢复、独立 10 USD 局部修复授权、33 USD 正式生产授权、逐镜验收和四项交付。成片 15.17 秒；3 个镜头均为 704×1280、24fps、121 帧/5.04 秒；三个 keyframe 共用 Canonical `64ad1657…` / SHA-256 `1a4c3233…`。Provider 未报告费用，保持 `not_reported`；用户明确接受主观模型质量限制用于端到端验证，不等同独立质量通过。 |
| 历史边界 | `0cb923f` 曾关闭 A2，但不是当前候选；只作为回归目标，不计入当前 HEAD 发布通过数 |

## Gate A：核心体验

| ID | 要求 | 必须证据 | 当前状态 | 下一动作 |
|---|---|---|---|---|
| A1 | 三入口、四阶段、四确认和变更预览 | 当前候选的真实后端浏览器 E2E | `PARTIAL` | Visual 2.0 canonical 路由和 Mock API E2E 已通过；补 authenticated live-stack |
| A2 | 快速/专业模式共享同一事实源 | 双模式读取同一版本、批次、预算和血缘 | `PARTIAL` | 在当前候选复现历史 A2 场景 |
| A3 | 试拍、生产和修复费用分别授权 | 真实请求、Reservation、ProviderOperation 和实际费用 | `PARTIAL` | 三类授权与 Reservation 已分别生效，所有付费媒体 operation 均 attempt 1、无重复 submit；Provider 未报告最终费用，继续保持 `not_reported`，等待账单口径核对 |
| A4 | Canonical 和必需参数进入有效请求 | Spy + 真实 EffectiveRequest/TranslationReport | `PASS` | shot-1/2/3 keyframe 均携带 Canonical `64ad1657…` + SHA-256；Agnes 图片 `1K/9:16`、视频 `9:16/24fps/121帧/5秒/无原生音频`，无 dropped options |
| A5 | 代表镜头真实暴露风险或支持继续 | 试拍 Artifact、Q0–Q6、限制和用户决定 | `PARTIAL` | 首次 video 503 和对象存储竞态形成硬阻断；产品生成局部修复，成功视频及首/中/末帧进入审阅，用户说明与自动限制分别保留；试拍/修复发生在当前候选之前 |
| A6 | 一个失败镜头被局部修复 | 新旧 NodeRun、复用 Artifact、额外授权和费用 | `PARTIAL` | Repair Batch `933ee4bc…` 只重跑 video、video_drift_review、composite、continuity_review；Canonical/Keyframe/Voice/Subtitle 复用；新 operation `49db23a6…` 单次成功，旧失败未删除；需在冻结 RC 的目标用户流程中自然复现，不为补证单独付费重跑 |
| A7 | 15–30 秒中文对白作品和四项交付 | 同一候选的多镜头真实全链 | `PASS` | Production Batch `7b760f99…` 完成 3 镜头、15.17 秒 MP4、SRT、timeline.json 和素材包；验收与导出精确引用 3 个 accepted Artifact |
| A8 | 三名目标用户无人代操作完成 | 三份脱敏用户记录 | `OPEN` | A7 稳定后安排三次测试 |
| A9 | 至少两人愿意保存、展示或继续创作 | A8 对应的结束问题原话 | `OPEN` | 与 A8 同步收集 |

## Quality Gate

| ID | 要求 | 当前状态 | 下一动作 |
|---|---|---|---|
| Q0 | 授权、能力、许可和参考有效 | `PASS` | 三类预算独立授权；冻结 Binding/Manifest、账号能力、Canonical 引用和一次性提交边界可追溯 |
| Q1 | 有效请求完整 | `PASS` | 真实 I2I/I2V 的 EffectiveRequest、TranslationReport、引用 ID/SHA、固定参数和无 dropped options 均持久化 |
| Q2 | 文件、尺寸、时长、音轨、黑帧和静音检查 | `PARTIAL` | MP4/SRT/timeline/ZIP 非空且哈希通过；三段视频与成片的尺寸、帧率、帧数、时长和音轨已探测；黑帧/静音专项仍未独立量化 |
| Q3 | 人物、外观、肢体和时序证据 | `PARTIAL` | Canonical 与首/中/末帧血缘完整；本轮按用户指示不以模型主观质量阻断，尚无独立视觉复核结论 |
| Q4 | 声音、说话人、口型和表演 | `PARTIAL` | post-dub 音轨、台词和限制已交付并记录用户覆盖理由；未宣称完成可信 lip-sync 或独立试听评估 |
| Q5 | 叙事、对白和连续性 | `PARTIAL` | 三镜故事与字幕完整交付且逐镜接受；独立目标用户对叙事和连续性的观察尚未收集 |
| Q6 | 用户验收和主观覆盖 | `PARTIAL` | Owner 在产品内逐镜接受并保留主观质量限制；三名目标用户无人代操作仍未执行 |
| Q7 | 身份、声音/口型、叙事三类修复演练 | `PARTIAL` | 已完成一次真实视频局部修复；身份、声音/口型、叙事三类独立修复演练仍未全部完成 |
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
| 2026-08-21 | A5, A6 | PARTIAL -> PARTIAL（真实链完成，候选边界未闭） | `214a527fb1a53a59d6fedc5d7e97dd6b9c62add1` | `tmp/p0-evidence/214a527fb1a53a59d6fedc5d7e97dd6b9c62add1/g5-repair/` | run_operator | 独立 10 USD 授权执行真实局部修复；ProviderOperation `49db23a6…` 在 Heavy Worker 停启后以同一远端 ID、attempt 1 恢复并成功；只重跑 video 与三个下游。证据候选不是当前 `faee665`，故发布 Gate 不升 PASS |
| 2026-08-21 | A4 | PARTIAL -> PASS | `faee665c1d53dd6c6f48064fbb2a6b6887efd91d` | `tmp/p0-evidence/faee665c1d53dd6c6f48064fbb2a6b6887efd91d/g9-production-delivery/` | run_operator | 三个 keyframe 真实请求均引用同一 Canonical Artifact ID/SHA-256；图片和视频 Binding/Manifest、EffectiveRequest、TranslationReport 与固定参数断言通过 |
| 2026-08-21 | A7 | OPEN -> PASS | `faee665c1d53dd6c6f48064fbb2a6b6887efd91d` | `tmp/p0-evidence/faee665c1d53dd6c6f48064fbb2a6b6887efd91d/g9-production-delivery/` | run_operator | 3 个 accepted 镜头精确导出为 15.17 秒 MP4、SRT、timeline.json 和素材包；20 个正式节点全部终态，付费媒体节点无重复 operation；主观模型质量按用户说明保留为限制，A8/A9 未执行 |
