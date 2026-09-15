# V1_STATUS — 当前状态权威

Status: current / Date: 2026-09-15（入口见 [CURRENT.md](CURRENT.md)）

## 当前发布判定：REL-01 真实验收全链通过，等待 Owner 合并

**候选**：`dev` = `d47d388`。产品代码（`backend/app`、`backend/alembic`、
`frontend/src`、`docker-compose.yml`）与接受真实验收的 `cd6f202` **逐树相同**
（`git rev-parse <sha>:<path>` 比对为 SAME），其后只有测试断言与验收驱动器变化。

**REL-01 真实 DS＋Agnes 验收：全部阶段 PASS**（Owner 授权付费、无预算上限；隔离候选栈
`dramaf-relcand`，仅发布 `127.0.0.1:8088`，`/health.source_commit = cd6f202`）：

| 阶段 | 结果 |
|---|---|
| `preflight` | PASS（Agnes `auth_models` 真实探测 200 passed，两条绑定 `account_verified`） |
| `story` | PASS（真实 DeepSeek，`actual_model=anthropic/deepseek-v4-flash`） |
| `media` | PASS（真实 Agnes 关键帧＋视频，逐片过身份/漂移审查与人工批准） |
| `editing` | PASS（交付准入逐片通过、剪辑建议采用可审计） |
| `regressions` | PASS（负向边界 fail closed、MANUAL 不依赖导演） |
| `delivery` | PASS（真实 MP4/SRT 下载、哈希一致、ffprobe 全真、15–30s、改字幕重导出零新增媒体调用） |
| `review-submit` / `review-collect` | PASS（修复候选已派发并停在人工门；`review_repair` 断言通过） |

成片证据：`template_auto-final-film.mp4` 6.34 MB、`free_assist-final-film.mp4` 3.77 MB，
各带 SRT，均在 `tmp/evidence/`。

## 本轮修复的产品缺陷（全部由真实验收暴露，离线套件此前全绿）

| 提交 | 缺陷 |
|---|---|
| `4e9113f` | Formal 选择门**不可能满足**：冻结图里没有审查节点，且关键帧阶段从不排队审查 → 设为正式关键帧对任何项目都 422，下游视频链随之停死 |
| `fcd19a2` | 审查 run 未写 `upstream_artifact_id`，而门正是按该键解析审查 → "审查已完成"被读成"没有审查" |
| `468d4a3` | 审查查找在有界分页里做选择，历史一多即"查无此审查" |
| `cd6f202` | 重复导出成片撞唯一约束报 `ARTIFACT_NOT_INDEPENDENT`（产品要求重复导出回读原结果） |
| `cef8402` | 两个 repair 端点在 `commit()` **之后**读状态；repair 表按 `app.current_project_id()` 做 RLS 且该变量是每事务的，新事务没有作用域 → 修复已建、第一步已派发并提交，响应却是 404 `repair request not found` |

## 发布流水线状态（2026-09-15 21:40 UTC）

**尚未发布**：本文件上节记录的是"候选可发布"，不是"已发布"；`dev → main` 合并与版本
tag 属 Owner（Agent 不自批自合）。上表未列的 `revise-unknown-free` /
`replace-template` / `recover-local-editing` 三个阶段需特定前置状态（未对账的提交、
并发 Artifact 竞争失败），本轮未构造，记录为未执行。

| 项 | 状态 |
|---|---|
| `dev` | `9d844d3` 起（含本节修复；PR #90 → `main` 已开，`BLOCKED`） |
| `main` | `c12c3df`（MinIO 镜像源修复，已由 Owner 合并） |
| tag `v0.1.0` | → `c12c3df`；**合并 PR #90 后须重指到新的 main tip**，否则 Release 跑的是不含下述修复的树 |
| Release 运行 `35020100821` | `Verify release source` + 镜像构建/冒烟/多平台推送 + SBOM + manifest 全部成功；`Create online and offline release bundles` 失败：`write dramaforge-offline-linux-amd64-v0.1.0/.docker_temp_738787394: no space left on device` |
| 修复一（磁盘） | 打包前新增 `Reclaim runner disk before packaging`（`docker image/container/builder prune`，保留已打 tag 的发布镜像） |
| 修复二（打包契约） | 离线包此前**不可安装**：`images.tar` 与 `release.env` 被写进 `dramaforge-offline-linux-amd64-v0.1.0/` 子目录，而 `install.sh --offline` / `install.ps1 -Offline` 只在自己所在目录找它们 → 用户按 DEPLOYMENT.md 解压后必然 `images.tar is missing`。现改为**扁平包**（归档根即安装目录）并单趟写出 `images.tar.gz`（`docker save \| gzip`），峰值磁盘从 2.12 GiB 降到 1.06 GiB（本地实测：6 镜像 `images.tar` 1090.8 MiB + `tar.gz` 1082.8 MiB）。`docker load` 直接接受该压缩流（实测 6 镜像全部载入） |

**当前唯一阻塞（账号级，非仓库缺陷）**：CI 与 Security 的每个 job 都在 2–9 秒内失败、
`runner_id = 0`、0 个 step、无日志；check-run annotation 原文为
`The job was not started because recent account payments have failed or your spending
limit needs to be increased. Please check the 'Billing & plans' section in your settings`。
托管 runner 无法分配 → CI/Security 无法变绿、Release 也无法重跑。解除需 Owner 在
GitHub Billing 处理付款方式或把 Actions spending limit 提到 $0 以上（仓库为 private，
免费额度耗尽后即为此状态）。

解除后按序执行：重跑 CI/Security 至全绿 → 合并 PR #90 → `git push --force origin
<new-main>:v0.1.0` 重指 tag（仅 tag，已在记录中声明）→ 重跑 Release（直接重跑
`35020100821`，不能用 `--failed`：bundle 失败使 checksums/artifact/attestation/GitHub
Release 全部 skipped）→ 执行 RELEASE.md 5–7 步 → 用发布的 `install.sh --offline`
在干净目录复核离线安装（本节修复只做过程序与结构验证，尚未对真实发布物执行）。

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
