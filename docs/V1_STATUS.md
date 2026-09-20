# V1_STATUS — 当前 V1 / 发布状态

Status: current  
本地运行与远端分支状态核对日期：2026-09-20。

## 当前结论

**首版尚未正式发布完成。** 运行候选、集成 PR 和发布基线必须分开看；本地质量门通过不等于真实双路径验收或正式发布完成。

| 对象 | 当前事实 |
|---|---|
| 发布基线 | `main` 为 `c12c3dfb89cca92a45de99a6db4ade2f0c5f19e7`；`dev` / PR #90 HEAD 为 `ca8f8b7555768b958fd372608aaf34c2ac430f3d`。PR #90 (`dev -> main`) 仍 OPEN、未合并 |
| 当前 8080 实例 | API、dispatcher、三个 worker 与 frontend 已切换到 `dc3056e99caf1a20484e39058a5d3d8d6a40cba7` 运行候选；`GET /health` 返回 `env=production`、`db=up`，服务健康。数据库迁移头为 `20260919_0073` |
| 优化分支集成 | `codex/workbench-optimization -> dev` 已建立 PR #94，保持 Draft，未合并。运行候选之后的 CI 分支策略与状态文档变更不属于当前运行镜像内容；最终 HEAD/checks 以该 PR 为准 |
| 本地质量门 | 运行候选已通过完整 backend/PostgreSQL/migration、frontend（含完整未分片 Playwright）与固定 LiteLLM mock-proxy 容器门。并行重负载下的前端超时未计为通过；通过记录来自原配置的独立完整重跑 |
| 真实制作验收 | 双路径真实验收 driver 已为 `complete=true`：模板和自由创作均完成 MP4/SRT；自由路径的一次授权 Editing 文本建议已显式采用、保存并导出，再完成仅剪辑重导出。双路径浏览器、刷新和独立登录恢复通过，重导出未新增远程图像/视频操作。既有媒体与中断恢复沿用有边界的候选等价证明并保留原始 SHA 归属，不宣称在新 SHA 重新生成全部媒体 |

CI 仅监听指向 `dev` / `main` 的 PR 与手动 dispatch；push 本身不是质量门证明。
PR #94 的远端检查不能替代 Owner 审查，PR #90 的旧检查也不覆盖优化分支。

## 当前继续边界

本次已完成运行候选的质量门、部署及双路径制作验收。Owner 授权的至多 ¥10、一次 Editing 文本建议已消费；没有额外文本重试或图像/视频生成授权。
UI 已验证建议采用不等于保存、显式保存/导出、播放和刷新恢复，最终收集断言全部通过。
不重跑已有图像/视频，不重试历史 `unknown_submission`。后续进入 Owner 候选审阅与发布流程；Agent 不批准或合并 PR，不发布。

## 已确定的首版产品边界

- `quality_gated` 表示质量认证/正式支持证据，不是普通执行与实验的硬准入；绑定、连接、能力不匹配仍失败关闭。
- 项目 Provider Binding 有只读回显；Provider Connection 可启用/停用，连接删除延期。
- 无生产者的旧 Shot Change Proposal 面板、不可达的 ProfessionalWorkbench 非实验分支和未消费的 ExperimentCompare 已移除；现行 Director Turn / Shot Suggestion 与 ExperimentBranch 路径保留。
- 镜头 6 的旧视频提交仍须按 `unknown_submission` 保留证据，禁止技术盲重试。新的用户重生成意图必须作为新操作独立授权。

## 尚需闭合的发布条件

1. **候选一致性**：由 Owner 确定最终候选；其运行相关内容需通过对应完整容器门和远端 required checks。后续优化不能夹带进旧候选验收。
2. **正式入口**：在明确安排现有实例交接后，让 8080 的 gateway/API/workers 都运行该候选的 production 身份。健康状态本身不证明创作链完成。
3. **REL-01 证据绑定**：当前运行候选的验收 driver 已为 `complete=true`，旧媒体/恢复证据通过明确的候选等价边界保留来源。Owner 仍需确认最终发布候选；若运行相关代码变化，须重新评估受影响证据，不能直接挪用当前结论。
4. **Owner 合并**：Owner 审阅并合并受保护的 `dev -> main`；agent 不批准、不合并。
5. **发布与安装**：成功生成版本化 Release 制品，并用该版本的 online/offline bundle 在干净目录安装验证。源码测试不能替代制品安装验证。

真实 Provider probe/production/repair 每次都需要本任务明确的正数预算与 Owner 授权。历史预算不延续，
可能已计费或 `unknown_submission` 的调用不能盲重试；当前正在运行的其他实例也不属于可自动清理的资源。

## 权威与历史

产品与技术合同见 [CURRENT.md](CURRENT.md)；可重复验证命令见 [DEVELOPMENT.md](DEVELOPMENT.md)、
[DEPLOYMENT.md](DEPLOYMENT.md) 与 [RELEASE.md](RELEASE.md)。先前工作区快照、旧测试计数、旧候选运行身份和逐轮执行记录
只通过 Git 历史追溯，不在本文件继续累积互相矛盾的“当前结论”。
