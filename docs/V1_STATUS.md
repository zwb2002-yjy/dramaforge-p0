# V1_STATUS — 当前 V1 / 发布状态

Status: current  
本地运行与远端分支状态核对日期：2026-09-22。Owner 拍板同日落盘（架构债顺序、死代码、demo、ADR/依赖、条件 3）。
迁移头以候选上 `alembic heads` 为准；当前树对应 **`20260922_0077`**（见
[DATA_MODEL.md](DATA_MODEL.md)）。

## 当前结论

**首版尚未正式发布完成。** 运行候选、集成 PR 和发布基线必须分开看；本地质量门通过不等于真实双路径验收或正式发布完成。

创作体验改进见 [开发合同](ARCHITECTURE_MAPPING.md#creation-improvement-contract)。
PR/MP/UI/RT 与 AC-01–AC-18 是目标要求，文档完成不代表开发、制作验收或发布完成。
新目标不能直接复用历史 `complete=true` 结论；最终候选须覆盖实际改动及新增验收。
该开发合同不自动扩张已有发布候选，纳入哪一个发布版本须在该候选范围中明确。

本文件**不钉死** PR 编号、测试计数或 Base SHA 作为长期事实（与 CURRENT.md「计数/SHA 不作当前事实」一致）。下表只描述**状态性质**；最终候选 SHA、门结果与证据路径在发布条件勾选表中由 Owner 落笔。

| 对象 | 当前事实 |
|---|---|
| 发布基线 | `main` 仅通过受保护的 `dev -> main` PR 前进；当前 tip 以远端为准 |
| 运行实例 | 8080 上的 gateway/API/workers 与迁移头构成「当前运行候选」；健康状态不证明创作链完成。实例身份、迁移头与源码 SHA 必须分别核对 |
| UI 候选 | 存在尚未合入的 UI/优化分支与 Draft PR；最终 HEAD/checks 以 PR 为准，不得把 Draft 检查计数写成已发布事实 |
| 本地质量门 | 完整 backend/PostgreSQL/migration、frontend（含完整 Playwright）与固定 LiteLLM mock-proxy 容器门可重复执行；命令见 [DEVELOPMENT.md](DEVELOPMENT.md) |
| 真实制作验收 | 双路径真实验收 driver 可达 `complete=true`（模板与自由创作 MP4/SRT；一次授权 Editing 文本建议显式采用/保存/导出）。历史媒体/恢复证据仅在「候选等价边界」内复用（见条件 3） |

CI 仅监听指向 `dev` / `main` 的 PR 与手动 dispatch；push 本身不是质量门证明。
Agent 不批准或合并 PR，不发布。

## 当前继续边界

- 质量门、部署与双路径制作验收的完成，不表示最新 UI 候选已正式发布。
- Owner 授权的历史付费预算不延续；没有新的正数预算与逐操作授权时不得扩大 probe/production/repair。
- 不重跑已有图像/视频，不重试历史 `unknown_submission`。新的用户重生成意图必须作为新操作独立授权。
- 后续进入 Owner 候选审阅与发布流程。

## 已确定的首版产品边界

- `quality_gated` 表示质量认证/正式支持证据，不是普通执行与实验的硬准入；绑定、连接、能力不匹配仍失败关闭。
- 项目 Provider Binding 已有显式绑定与来源回显；Provider Connection 可启用/停用，连接删除延期。多连接与来源隔离的目标改造见 MODEL_PROVIDER。
- 无生产者旧表面已清退：Shot Change Proposal 面板和前端客户端已删除；服务端 `change-proposals` API 暂保留且无前端消费者。ModelPicker/uiStore/DirectorBoard 前端死代码删除；video-frames 保留；DirectorBoard 后端暂保留；V2 bootstrap stub fail-closed 为类型化 `unsupported_capability`（HTTP 422），不再以 500 暴露。产品运行时无 demo Project ID 特判，测试使用普通 Project fixture。
- 镜头旧视频提交仍须按 `unknown_submission` 保留证据，禁止技术盲重试。

## 尚需闭合的发布条件（Owner 勾选表）

每条必须能落到：**最终候选 SHA + 可执行门命令 + 证据路径 + Owner 勾选**。
未勾选不得宣称 V1 发布完成。

| # | 条件 | 门命令 / 证据 | Owner 确认 |
|---|---|---|---|
| 1 | **候选一致性**：确定最终候选 SHA；其运行相关内容通过完整容器门与远端 required checks。后续优化不得夹带进旧候选验收 | 候选 SHA：`________`；`scripts/run_quality_in_docker.ps1`；远端 required checks 截图或 API 结果路径：`________` | ☐ |
| 2 | **正式入口**：在明确安排现有实例交接后，8080 的 gateway/API/workers 都运行该候选的 production 身份；`alembic heads` 单一且与候选一致 | 实例源码 commit：`________`；`GET /health` 证据路径：`________`；`alembic heads` 输出：`________` | ☐ |
| 3 | **候选验收证据绑定**：针对**最终候选 SHA** 记录质量门命令、运行结果和证据路径。历史媒体/恢复证据只有在明确列出「候选等价边界」（哪些文件/路径自证据 SHA 起未变化）并确认相关代码未变化时才允许复用；运行相关代码一旦变化须重新评估受影响证据，不能直接挪用 | 最终候选 SHA 的验收 driver / 门日志路径：`________`；候选等价边界清单路径：`________` | ☐ |
| 4 | **Owner 合并**：Owner 审阅并合并受保护的 `dev -> main` | 合并提交 SHA：`________` | ☐ |
| 5 | **发布与安装**：生成版本化 Release 制品，并用该版本 online/offline bundle 在干净目录安装验证。源码测试不能替代制品安装验证 | Release tag：`________`；安装验证日志路径：`________` | ☐ |

当前尚无版本化 GitHub Release。默认分支仍有 3 条开发依赖安全告警（`js-yaml` high、`vitest` / `@vitest/mocker` moderate）；生产 `npm audit --omit=dev --audit-level=high` 为零漏洞不等于这些告警已关闭。依赖策略：优先兼容升级关闭；无安全兼容版本时记有期限例外并写明到期日。依赖文件变化或目标为 `main` 的 PR 自动运行 dependency-review，不依赖仓库变量开关；Dependabot 使用 direct + 非 major + 月度 + 限流。

真实 Provider probe/production/repair 每次都需要本任务明确的正数预算与 Owner 授权。历史预算不延续；可能已计费或 `unknown_submission` 的调用不能盲重试。

## 权威与历史

产品与技术合同见 [CURRENT.md](CURRENT.md)；可重复验证命令见 [DEVELOPMENT.md](DEVELOPMENT.md)、
[DEPLOYMENT.md](DEPLOYMENT.md) 与 [RELEASE.md](RELEASE.md)。先前工作区快照、旧测试计数、旧候选运行身份和逐轮执行记录
只通过 Git 历史追溯，不在本文件继续累积互相矛盾的“当前结论”。
