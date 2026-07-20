# Task 合同：S1-CONTRACT

**状态：SUPERSEDED / S1 阶段 Gate 未通过**

**日期：2026-07-20（2026-07-21 TRUTH-0.1 更正）**

**完成说明：** 本文仅定义 S1 切片合同与 `S1.1` 启动范围。**不得**将本文状态理解为 S1 阶段完成。S1 Gate（RLS、真 Outbox/Redis、完整 creation Brief、双模式壳等）仍未通过。后续执行以 `docs/开发执行检查点.md` READY 队列为准（`S1-DB-0.1` 起）。

**前置：`RECOVERY-0.1` COMPLETED；BOOT-0 容器 / Git remote / S0-A fixture 可仍为 PAUSED**

## 1. 完成效果

S1（可信基础骨架与双模式应用壳）被拆成可独立验收的纵向 Task；每个 Task 有可观察效果、证据命令、文件所有权与完成定义。合同落地后立即启动 **`S1.1-access-session`**，不因缺少 Docker/远端而等待用户“继续”（集成测试在无 PG 时可先写失败/跳过策略，但不得伪造 RLS 通过）。

## 2. 范围

- 对齐 `agent.md` S1 Gate 与 `04` 中 access / events / production graph / creation 相关字段边界
- 定义切片顺序、依赖、与 PAUSED 项的关系
- 指定首个 READY 实现 Task 的详细合同（§5）

## 3. 非范围

- 不在本 Task 内写完 S1 业务代码
- 不实现 S2–S5、真实 Provider、S0-A 样本
- 不把 BOOT-0 容器 Gate 标为通过

## 4. S1 Gate 验收映射（阶段级，非本 Task 完成条件）

S1 阶段完成仍需全部满足 `agent.md` S1 Gate，包括但不限于：

- 两用户跨项目读写 / Worker / 对象 URL 越权拒绝
- RLS 连接池上下文无泄漏
- Outbox 重放、死信、SSE `Last-Event-ID`
- Graph 发布不可变
- 双入口打开同一 Project
- 未规划授权时文本 ProviderOperation 为零

上述由 `S1.1`–`S1.6` 累积满足，**禁止**在任一子 Task 完成时宣称 S1 阶段完成。

## 5. 第一个 READY Task：`S1.1-access-session`

### 5.1 完成效果

系统具备最小 access 边界：可创建/读取 Organization、User、Membership；HTTP 会话（Cookie）与 CSRF 保护可测；未认证请求被拒绝。尚未要求完整 BYOK 加密轮换 UI。

### 5.2 范围

- Alembic 首迁：仅 `04` 中 S1.1 所需表的**全量字段**（不得简化列）
- ORM / Pydantic / API 路由（Route → Service → Repository）
- Cookie 会话签发与校验、CSRF
- 单元 + 可运行集成测试（有 PostgreSQL 时跑 RLS 预备断言；无 PG 时集成测试标记 skip 并在检查点诚实记录，**不得**用 SQLite 冒充 RLS）

### 5.3 非范围

- Project 表全量与跨项目 RLS 矩阵（→ `S1.2`）
- Outbox / Graph / Creation 物化
- 前端登录完整产品化（可先 API + 最小测）

### 5.4 验收证据

- 迁移 upgrade/downgrade 在真实 PostgreSQL 上可跑（Docker 或本机 PG）；若均不可用 → Task 实现代码可合并但 Gate 项 `S1.1-PG` 记 PAUSED，不得标阶段完成
- pytest：未认证 401；CSRF 失败拒绝写；会话 cookie 往返
- ruff / mypy 通过
- OpenAPI 类型重新生成并提交

### 5.5 文件所有权（单写入）

- `backend/app/access/**`
- `backend/app/api/v1/auth.py`（及 router 注册）
- `backend/app/shared/security.py`、`db.py` 最小扩展
- `backend/alembic/versions/*`（本切片迁移）
- 对应 `backend/tests/**`
- 不改 frontend 业务页（除非最小 health 级）

### 5.6 完成定义

合同 §5.2–5.4 全部满足或缺口被诚实 PAUSED；检查点更新；账本 `S1.1-access-session` COMPLETED 后方可启动 `S1.2-project-rls`。

## 6. 后续切片（摘要）

| ID | 效果 |
|---|---|
| `S1.2-project-rls` | Project + RLS 跨项目拒绝 + Worker 上下文 |
| `S1.3-event-outbox` | EventLog + Outbox 同事务 + 重放/死信骨架 |
| `S1.4-graph-model` | Graph/GraphVersion 不可变发布 |
| `S1.5-creation-shell` | Creation Interface + 无 Key 手工路径 + 无 Provider |
| `S1.6-frontend-dual-entry` | 快速/专业入口共享 ProjectSnapshot |

## 7. 本 Task 完成定义

- [x] 本文已提交
- [x] `docs/开发执行检查点.md` 的**当前唯一执行任务**为 `S1.1-access-session`（非本合同 ID）
- [x] 账本：`S1-CONTRACT` COMPLETED；`S1.1-access-session` STARTED
- [x] 文首状态与检查点队列、账本三者一致为 COMPLETED
