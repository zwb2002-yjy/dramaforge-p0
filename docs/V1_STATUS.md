# V1_STATUS — 当前状态权威

Status: current / Date: 2026-09-15（入口见 [CURRENT.md](CURRENT.md)）

## 当前发布判定：REL-01 真实验收已跑通主管道，剩余一处 legacy 端点缺陷

**候选**：`dev` = `9496bf2`。产品代码（`backend/app`、`backend/alembic`、
`frontend/src`、`docker-compose.yml`）与接受真实验收的 `cd6f202` **逐树相同**
（`git rev-parse <sha>:<path>` 比对为 SAME），`9496bf2` 之后只有测试断言与验收
驱动器变化。

**REL-01 真实 DS＋Agnes 验收**（Owner 授权付费、无预算上限；隔离候选栈
`dramaf-relcand`，仅发布 `127.0.0.1:8088`，`/health.source_commit = cd6f202`）：

| 阶段 | 结果 |
|---|---|
| `preflight` | PASS（Agnes `auth_models` 真实探测 200 passed，两条绑定 `account_verified`） |
| `story` | PASS（真实 DeepSeek，`actual_model=anthropic/deepseek-v4-flash`） |
| `media` | PASS（真实 Agnes 关键帧＋视频，逐片过身份/漂移审查与人工批准） |
| `editing` | PASS（交付准入逐片通过、剪辑建议采用可审计） |
| `regressions` | PASS（负向边界 fail closed、MANUAL 不依赖导演） |
| `delivery` | PASS（真实 MP4/SRT 下载、哈希一致、ffprobe 全真、15–30s、改字幕重导出零新增媒体调用） |
| `review-submit` | **未通过**：legacy `POST …/repair` 返回 404 `repair request not found` |

该 404 的定位（探针已还原，仓库干净）：服务层成功、失败发生在响应读回阶段、按 ID
计数为 0 行、同路径进程内直调成功。**根因未确定，不作为已解决记录**。分阶段修复
端点（`POST …/repairs`、`…/repairs/{id}/steps`）可用且已由 PG 集成测试与候选上的
manual 全链覆盖；失败发生在任何 Provider 调用之前，无未知提交、无重复计费。

本轮同时修复并推送的产品缺陷（均由真实验收暴露，离线套件曾全绿）：

- `4e9113f`：Formal 选择门不可能满足——图里没有审查节点，且关键帧阶段从不排队审查；
- `fcd19a2`：审查 run 未写 `upstream_artifact_id`，门按该键解析审查；
- `468d4a3`：审查查找在有界分页里做选择，历史一多即"查无此审查"；
- `cd6f202`：重复导出成片撞唯一约束报 `ARTIFACT_NOT_INDEPENDENT`。

**尚未完成**：`dev → main` 合并与版本 tag 属 Owner（Agent 不自批自合）；上表未列
的 `revise-unknown-free` / `replace-template` / `recover-local-editing` 三个阶段需
特定前置状态，本轮未构造，记录为未执行。本文件记录的是"候选可发布"，不是"已发布"。

实施记录（不入 Git）见 `tmp/v1-release-20260915/`：`REL01_RESULT_cd6f202.md`、
`CANDIDATE_RECORD.md` 及各 DEV-0x_RECORD.md。

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

- Alembic 单 head：`20260915_0069`（69 个 revision）；以候选自身 `alembic heads`
  为准。本轮新增 0067（资产入库请求身份）、0068（人工审查决定）、0069（分阶段修复步骤）。
- CI：`policy` + `container-gates`（backend / PostgreSQL / 迁移 / OpenAPI /
  前端 / E2E / LiteLLM 集成），Release workflow 发布版本化镜像。

## 剩余工作方向

- Owner 审阅并合并发布 PR **#88**（候选 `df546f6`，检查已全绿）；Agent 不自批自合。
- DS＋Agnes 真实场景验收：按仓库规则需要逐次正数预算与 Owner 授权。
- 发布按 [RELEASE.md](RELEASE.md) 执行；新功能开发以本目录权威文档 + 代码
  现状为基线，不再有历史 Task Contract 序列。

## 历史证据的获取方式

已删除的 Task Contract、Review、Golden evidence 与执行记录保存在 Git 历史
（`git log` / `git show`）中；它们不构成当前实现依据。正式验收证据按
[DEVELOPMENT.md](DEVELOPMENT.md) 写入 `tmp/p0-evidence/<source-commit>/`
（不入 Git）。
