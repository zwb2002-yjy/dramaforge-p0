# V1_STATUS — 当前 V1 / 发布状态

Status: current  
本地状态核对日期：2026-09-20；远端候选与检查记录仍以表中 2026-09-19 的核对为准。

## 当前结论

**首版尚未正式发布完成。** 发布候选、当前运行实例和后续源码优化必须分开看，不能用旧测试数字或健康检查替代发布验收。

| 对象 | 当前事实 |
|---|---|
| 冻结的运行候选 | 2026-09-19 核对：`8354198`；`dev` / PR #90 HEAD 为 `ca8f8b7555768b958fd372608aaf34c2ac430f3d`。两提交之间只有本状态文档变化，运行内容未变 |
| PR #90 | 2026-09-19 核对：`dev -> main` 为 OPEN、未合并；`main` 基线为 `c12c3dfb`。仅 Owner 可审阅并合并 |
| GitHub 检查 | 2026-09-19 读取 PR 检查结果：`policy`、`container-gates`、`secret-scan`、Python/前端依赖审计、`filesystem-scan` 均为 SUCCESS。旧的 hosted runner 阻塞不再是当前结论 |
| 当前 8080 实例 | 运行此前基于 dirty 工作区构建的本地优化版：API/workers 为 `dramaforge-ui-runtime:20260919-tts`，前端为 `dramaforge-ui-frontend:20260919-tts-r3`。只读 `GET /health` 返回 `env=development`、`source_commit=local-ui-ca8f8b7-dirty-tts-927700584c54`、`db=up`；不是冻结候选的正式 production 身份 |
| 后续源码优化 | 保存在 `codex/workbench-optimization` 开发分支，未并入 `dev`，不是当前 8080 镜像内容。TTS、供应商与相关 UI 已有定向回归和单镜头配音/成片验证；后续返修与恢复改动仍需本候选完整质量门、真实多镜头旅程及异常恢复验收。旧候选的 GitHub 成绩不覆盖这些改动；由 Owner 决定新的发布候选 |

CI workflow 仅监听指向 `dev` / `main` 的 PR 与手动 dispatch；push 本身不是质量门通过证明。
上述 GitHub 成功记录属于所列 HEAD，不自动覆盖新的分支改动，也不等同于 Release workflow 成功。

## 当前开发暂停边界

当前授权仅收口三个稳定性问题并保存开发分支：Provider 恢复扫描不再排入繁忙的媒体队列；
轮询超时主动让出时释放执行租约，使取消能接续核对同一远端任务；返修读取刷新跨会话的任务事实。
定向回归不等于完整候选验收。本轮不更新 8080、不执行业务数据库迁移、不进行新的付费生成，
也不合并或发布。完整质量门、更新实例和真实 UI 制作验收留待下一次明确继续。

## 已确定的首版产品边界

- `quality_gated` 表示质量认证/正式支持证据，不是普通执行与实验的硬准入；绑定、连接、能力不匹配仍失败关闭。
- 项目 Provider Binding 有只读回显；Provider Connection 可启用/停用，连接删除延期。
- 无生产者的旧 Shot Change Proposal 面板、不可达的 ProfessionalWorkbench 非实验分支和未消费的 ExperimentCompare 已移除；现行 Director Turn / Shot Suggestion 与 ExperimentBranch 路径保留。
- 镜头 6 的旧视频提交仍须按 `unknown_submission` 保留证据，禁止技术盲重试。新的用户重生成意图必须作为新操作独立授权。

## 尚需闭合的发布条件

1. **候选一致性**：由 Owner 确定最终候选；其运行相关内容需通过对应完整容器门和远端 required checks。后续优化不能夹带进旧候选验收。
2. **正式入口**：在明确安排现有实例交接后，让 8080 的 gateway/API/workers 都运行该候选的 production 身份。健康状态本身不证明创作链完成。
3. **REL-01**：在同一候选完成真实媒体、浏览器旅程、异常恢复与跨阶段证据收集，最终由验收 driver 证明 `complete=true`；不伪造缺少的断言或复用不匹配 SHA 的证据。
4. **Owner 合并**：Owner 审阅并合并受保护的 `dev -> main`；agent 不批准、不合并。
5. **发布与安装**：成功生成版本化 Release 制品，并用该版本的 online/offline bundle 在干净目录安装验证。源码测试不能替代制品安装验证。

真实 Provider probe/production/repair 每次都需要本任务明确的正数预算与 Owner 授权。历史预算不延续，
可能已计费或 `unknown_submission` 的调用不能盲重试；当前正在运行的其他实例也不属于可自动清理的资源。

## 权威与历史

产品与技术合同见 [CURRENT.md](CURRENT.md)；可重复验证命令见 [DEVELOPMENT.md](DEVELOPMENT.md)、
[DEPLOYMENT.md](DEPLOYMENT.md) 与 [RELEASE.md](RELEASE.md)。先前工作区快照、旧测试计数、旧候选运行身份和逐轮执行记录
只通过 Git 历史追溯，不在本文件继续累积互相矛盾的“当前结论”。
