# Release Gate Board

**状态：LIVE / 发布证据看板，不定义产品合同**

**最近复核：2026-08-19**

本看板执行 [`../current/01-产品与发布契约.md`](../current/01-产品与发布契约.md)、[`../current/03-质量与验证体系.md`](../current/03-质量与验证体系.md) 和 [`../current/04-执行路线图.md`](../current/04-执行路线图.md)。架构证明另见 [`../current/02-运行时与领域架构.md`](../current/02-运行时与领域架构.md#14-架构确认表)。

`PASS` 必须绑定一个干净候选 commit 和要求的证据类型。Mock、Spy、旧 P0、其他 commit 或口头结论不能替代真实 Provider、目标用户、离线硬件和安装证据。脱敏证据写入 `tmp/p0-evidence/<source-commit>/`；任何真实付费请求前必须执行 [`real-provider-evidence-preflight.md`](real-provider-evidence-preflight.md) 并获得单次书面授权。

## 当前候选边界

| 字段 | 当前事实 |
|---|---|
| 运行候选 | `1d921fb5b332f0809f9b9924872e619030459de2` (`dev`) |
| 当前候选 | `1d921fb`；运行中的 API、Dispatcher、两个 Worker 与 Frontend 同源，数据库 head `20260819_0028` |
| 自动化基线 | 当前候选后端全量 `642 passed / 16 skipped`、Unified/Provider 聚焦 `115 passed`、隔离 PostgreSQL migration `2 passed`、前端 `56 passed`、typecheck/build、Ruff/mypy 通过；Chromium `11/11`；候选镜像内 G2 smoke 与 NodeRun source commit 数据库事实通过；同源 Docker Compose 栈健康 |
| 真实证据 | 一个 Agnes 真实视频镜头被 Q3 人工拒绝；`2026-08-20` 单次、`0.01 CNY` 上限 Agnes 图片 v2 `image_i2i` 账号 Probe 通过，Binding 已 account-verified，成本未报告；当前 HEAD 仍没有新的 Director I2I Artifact、完整试拍、修复、全片或用户测试 |
| 历史边界 | `0cb923f` 曾关闭 A2，但不是当前候选；只作为回归目标，不计入当前 HEAD 发布通过数 |

## Gate A：核心体验

| ID | 要求 | 必须证据 | 当前状态 | 下一动作 |
|---|---|---|---|---|
| A1 | 三入口、四阶段、四确认和变更预览 | 当前候选的真实后端浏览器 E2E | `PARTIAL` | Visual 2.0 canonical 路由和 Mock API E2E 已通过；补 authenticated live-stack |
| A2 | 快速/专业模式共享同一事实源 | 双模式读取同一版本、批次、预算和血缘 | `PARTIAL` | 在当前候选复现历史 A2 场景 |
| A3 | 试拍、生产和修复费用分别授权 | 真实请求、Reservation、ProviderOperation 和实际费用 | `PARTIAL` | 已完成一次明确授权的账号 Probe，仍需新授权下的真实 Director I2I 和账本/ProviderOperation 证据 |
| A4 | Canonical 和必需参数进入有效请求 | Spy + 真实 EffectiveRequest/TranslationReport | `PARTIAL` | G2 Spy 已证明 Canonical/首帧 ID 与 SHA-256、严格参数、EffectiveRequest、TranslationReport 和空 dropped_options；账号 Probe 仅证明本账号 I2I 能力，仍需独立授权下的真实 Unified Director I2I |
| A5 | 代表镜头真实暴露风险或支持继续 | 试拍 Artifact、Q0–Q6、限制和用户决定 | `PARTIAL` | 现有 Agnes 失败镜头补齐产品内验收证据 |
| A6 | 一个失败镜头被局部修复 | 新旧 NodeRun、复用 Artifact、额外授权和费用 | `OPEN` | 对现有失败镜头执行一次授权修复 |
| A7 | 15–30 秒中文对白作品和四项交付 | 同一候选的多镜头真实全链 | `OPEN` | 完成 1 主角、3 镜头黄金样本 |
| A8 | 三名目标用户无人代操作完成 | 三份脱敏用户记录 | `OPEN` | A7 稳定后安排三次测试 |
| A9 | 至少两人愿意保存、展示或继续创作 | A8 对应的结束问题原话 | `OPEN` | 与 A8 同步收集 |

## Quality Gate

| ID | 要求 | 当前状态 | 下一动作 |
|---|---|---|---|
| Q0 | 授权、能力、许可和参考有效 | `OPEN` | 图片 v2 Binding 已创建但未验证、未质量门禁；官方 `0 CNY/image` 价格快照、虚构 Canonical ID/SHA-256/MIME/尺寸、服务条款与隐私政策哈希已核验；免费层交互可能用于模型改进且发布用途仍需负责人复核；preflight 当前仅因缺单次书面授权而 BLOCKED |
| Q1 | 有效请求完整 | `PARTIAL` | 收集当前候选真实请求与参考注入证据 |
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
