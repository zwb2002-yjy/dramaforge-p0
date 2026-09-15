# V1_STATUS — 当前状态权威

Status: current / Date: 2026-09-15（入口见 [CURRENT.md](CURRENT.md)）

## 当前发布判定：待修复与候选重新验收

2026-09-15 静态核对的代码基线为 `dev` / `5ea45d6373d840d37f34a472b3dbe4853da9f8e6`。
当前工作区存在未提交文档；本轮没有运行正式门、真实 Provider 验收或查询远端 PR。
[产品闭环审计](PRODUCT_CLOSURE_AUDIT.md) 报告了候选证据缺失、真实渲染验证不足、
Review/Repair 与导演入口等阻塞，不能沿用祖先候选的“已验证待发布”作为当前结论。

发布范围与后续实施分别见 [设计](V1_RELEASE_DESIGN.md) 和
[执行](V1_RELEASE_EXECUTION.md)。下列完成记录仅适用于其注明的历史候选。

## 历史 V1 主链验收记录

V1"统一创作主链"目标（2026-09-03 起）已完成 21 项最终完成审计，全部 PASS。
运行时候选 `adf1b94`，证据/发布候选 `3677430`，`dev → main` PR #66 待 Owner
审阅合并。审计覆盖（摘要）：

- Legacy 硬删除与 Canonical/directory 门；
- Idea → proposal/diff/partial apply → Canonical facts；
- Template Start / Free Start 创建同一 Project；无模板 runtime；
- AUTO / ASSIST / MANUAL 保持执行身份；MANUAL 无导演回归通过；
- 主动推荐（performance/action/camera/shot/rhythm/reference）与
  whole/partial/reject 决策；
- Manual/locked/dirty/stale 优先级；
- Candidate/Formal/Experiment/Repair 边界；
- 统一 NodeRun/ProviderOperation/Artifact 血缘；
- OpenCut/Editing 为正式尾部，两路径 Final Film（H.264/AAC + SRT）真实交付；
- 全量质量/安全/迁移/E2E 与 commit-bound 真实 Provider Golden。

## 历史 Director Runtime（D0–D8）完成记录

独立导演编排 runtime（Owner 2026-09-09 授权）已落地：runtime contracts、
event boundary、invocation journal、LangGraph 验证、engine 迁移、
tools/decisions UI、跨 runtime 失败矩阵、候选验收与终态对账。MANUAL 路径
在导演服务停止时完成空项目 → MP4/SRT 全程。详见
[DIRECTOR_RUNTIME.md](DIRECTOR_RUNTIME.md)。

## 之后已合入 dev 的工作

- V2 导航 / Project Lobby / 设置返回语义（统一导航与项目大厅）；
- Resonance UI、Canvas-first UI、Production 渐进披露、移动端 canvas 收敛；
- 前端骨架对齐（设计 Token 采用、骨架约定落文档）；
- 上下文导演交互与项目导航修复（当时记录的 HEAD 为 070faa3）。

## 数据库与质量基线

- Alembic 单 head：`20260910_0066`（66 个 revision）。
- CI：`policy` + `container-gates`（backend / PostgreSQL / 迁移 / OpenAPI /
  前端 / E2E / LiteLLM 集成），Release workflow 发布版本化镜像。

## 剩余工作方向

- 按发布执行文档补齐阻塞并冻结新的干净候选，重新绑定正式验收证据；
- Owner 审阅实际发布 PR（历史记录中的 PR #66 状态未在本轮远端核实）；
- 发布按 [RELEASE.md](RELEASE.md) 执行；新功能开发以本目录权威文档 + 代码
  现状为基线，不再有历史 Task Contract 序列。

## 历史证据的获取方式

已删除的 Task Contract、Review、Golden evidence 与执行记录保存在 Git 历史
（`git log` / `git show`）中；它们不构成当前实现依据。正式验收证据按
[DEVELOPMENT.md](DEVELOPMENT.md) 写入 `tmp/p0-evidence/<source-commit>/`
（不入 Git）。
