# V1_STATUS — 当前状态权威

Status: current / Date: 2026-09-14（入口见 [CURRENT.md](CURRENT.md)）

## V1 主链状态：已验证待 Owner 合并发布

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

## Director Runtime（D0–D8）：已完成

独立导演编排 runtime（Owner 2026-09-09 授权）已落地：runtime contracts、
event boundary、invocation journal、LangGraph 验证、engine 迁移、
tools/decisions UI、跨 runtime 失败矩阵、候选验收与终态对账。MANUAL 路径
在导演服务停止时完成空项目 → MP4/SRT 全程。详见
[DIRECTOR_RUNTIME.md](DIRECTOR_RUNTIME.md)。

## 之后已合入 dev 的工作

- V2 导航 / Project Lobby / 设置返回语义（统一导航与项目大厅）；
- Resonance UI、Canvas-first UI、Production 渐进披露、移动端 canvas 收敛；
- 前端骨架对齐（设计 Token 采用、骨架约定落文档）；
- 上下文导演交互与项目导航修复（当前 HEAD 070faa3）。

## 数据库与质量基线

- Alembic 单 head：`20260910_0066`（66 个 revision）。
- CI：`policy` + `container-gates`（backend / PostgreSQL / 迁移 / OpenAPI /
  前端 / E2E / LiteLLM 集成），Release workflow 发布版本化镜像。

## 剩余工作方向

- Owner 审阅合并 PR #66（V1 发布闭环）；
- 发布按 [RELEASE.md](RELEASE.md) 执行；新功能开发以本目录权威文档 + 代码
  现状为基线，不再有历史 Task Contract 序列。

## 历史证据的获取方式

已删除的 Task Contract、Review、Golden evidence 与执行记录保存在 Git 历史
（`git log` / `git show`）中；它们不构成当前实现依据。正式验收证据按
[DEVELOPMENT.md](DEVELOPMENT.md) 写入 `tmp/p0-evidence/<source-commit>/`
（不入 Git）。
